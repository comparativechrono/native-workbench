#include "workbench.h"
#include <commctrl.h>
#include <objidl.h>
#include <gdiplus.h>
#include <shobjidl.h>
#include <shellapi.h>
#include <uxtheme.h>
#include <windowsx.h>
#include <algorithm>
#include <cmath>
#include <cerrno>
#include <cwchar>
#include <cwctype>
#include <exception>
#include <map>
#include <memory>
#include <stdexcept>
#include <thread>
#include <utility>

namespace {
constexpr UINT MSG_INITIALIZE = WM_APP + 1, MSG_LOG = WM_APP + 2,
    MSG_PHASE = WM_APP + 3, MSG_COMPLETE = WM_APP + 4;
constexpr UINT_PTR TIMER_ELAPSED = 1;
constexpr COLORREF CANVAS = RGB(245,247,251), PAPER = RGB(255,255,255),
    INK = RGB(27,38,58), MUTED = RGB(99,112,133), LINE = RGB(224,230,239),
    SIDEBAR = RGB(236,240,247);
enum : int { ID_PACK = 101, ID_ADD_PACK, ID_WORKFLOW, ID_OUTPUT, ID_PICK_OUTPUT,
    ID_RUN, ID_CANCEL, ID_OPEN_RESULTS, ID_CHECK, ID_DETAILS, ID_PREV, ID_NEXT,
    ID_WHEEL, ID_FORM, ID_FIELD = 1000 };

struct Completion { bw::Result result; bool imported = false; bw::Pack pack; };
std::wstring control_text(HWND control) {
    int length = GetWindowTextLengthW(control);
    std::wstring value(static_cast<size_t>(length) + 1, L'\0');
    int copied = GetWindowTextW(control, value.data(), length + 1);
    value.resize(static_cast<size_t>(std::max(0, copied))); return value;
}
std::wstring lower(std::wstring value) {
    for (auto& character : value) character = static_cast<wchar_t>(std::towlower(character));
    return value;
}
std::wstring lines_to_lf(const std::wstring& value) {
    std::wstring result;
    for (size_t i=0; i<value.size(); ++i) {
        if (value[i]==L'\r') { result += L'\n'; if (i+1<value.size() && value[i+1]==L'\n') ++i; }
        else result += value[i];
    }
    return result;
}
std::wstring lines_to_crlf(const std::wstring& value) {
    std::wstring result;
    for (wchar_t c : lines_to_lf(value)) { if (c==L'\n') result+=L'\r'; result+=c; }
    return result;
}
void post_text(HWND window, UINT message, const std::wstring& value) {
    auto text = std::make_unique<std::wstring>(value);
    if (PostMessageW(window,message,0,reinterpret_cast<LPARAM>(text.get()))) text.release();
}
std::wstring exception_message(const std::exception& exception) {
    try { return bw::utf16(exception.what()); }
    catch (...) { return L"The task failed. Its error message could not be decoded."; }
}
COLORREF colorref(uint32_t rgb) { return RGB((rgb>>16)&255,(rgb>>8)&255,rgb&255); }
Gdiplus::Color color(COLORREF c, BYTE alpha=255) { return Gdiplus::Color(alpha,GetRValue(c),GetGValue(c),GetBValue(c)); }
COLORREF mix(COLORREF a, COLORREF b, unsigned weight) {
    return RGB((GetRValue(a)*weight+GetRValue(b)*(100-weight))/100,
        (GetGValue(a)*weight+GetGValue(b)*(100-weight))/100,
        (GetBValue(a)*weight+GetBValue(b)*(100-weight))/100);
}
COLORREF contrast_text(COLORREF background) {
    auto channel=[](BYTE value){double n=value/255.0;return n<=0.04045?n/12.92:std::pow((n+0.055)/1.055,2.4);};
    const double luminance=0.2126*channel(GetRValue(background))+0.7152*channel(GetGValue(background))+0.0722*channel(GetBValue(background));
    // Use the darker ink for pale pack colours and white for dark colours.
    return luminance>0.179?RGB(0,0,0):PAPER;
}
void round_path(Gdiplus::GraphicsPath& path, float x,float y,float w,float h,float radius) {
    const float d=std::min(radius*2,std::min(w,h));
    path.AddArc(x,y,d,d,180,90); path.AddArc(x+w-d,y,d,d,270,90);
    path.AddArc(x+w-d,y+h-d,d,d,0,90); path.AddArc(x,y+h-d,d,d,90,90); path.CloseFigure();
}
void rounded(Gdiplus::Graphics& g,float x,float y,float w,float h,float radius,COLORREF fill,COLORREF stroke=CLR_INVALID) {
    Gdiplus::GraphicsPath path; round_path(path,x,y,w,h,radius);
    Gdiplus::SolidBrush brush(color(fill)); g.FillPath(&brush,&path);
    if(stroke!=CLR_INVALID) { Gdiplus::Pen pen(color(stroke),1.0f); g.DrawPath(&pen,&path); }
}

// BEGIN PORTABLE WORKFLOW GEOMETRY
// Text heights are measured by the native font renderer before this calculation.
// Exceptional long descriptions move into the scrollable form, retaining all text.
constexpr int MIN_WORKSPACE_WIDTH=800, MIN_WORKSPACE_HEIGHT=480;
struct WorkflowGeometry {
    int description_y=0, steps_y=0, outputs_y=0;
    int card_top=0, form_top=0, form_bottom=0, log_top=0, log_height=0;
    bool summaries=false, metadata_in_form=false, log_replaces_form=false;
};
WorkflowGeometry workflow_geometry(int text_top,int output_top,int description_height,
    int steps_height,int outputs_height,bool compact,bool show_details) {
    constexpr int card_heading=47, minimum_form=72, gap=10;
    WorkflowGeometry result;result.description_y=text_top;
    const int bottom=output_top-18;
    int after_description=text_top+(description_height?description_height+gap:0);
    result.steps_y=after_description;
    result.outputs_y=after_description+(steps_height?steps_height+6:0);
    const int after_summaries=result.outputs_y+(outputs_height?outputs_height+gap:0);
    result.summaries=!compact && after_summaries+card_heading+minimum_form<=bottom;
    result.card_top=result.summaries?after_summaries:after_description;
    if(result.card_top+card_heading+minimum_form>bottom) {
        result.metadata_in_form=true;result.summaries=false;
        result.card_top=text_top;
    }
    result.form_top=result.card_top+card_heading;
    result.form_bottom=bottom;
    if(show_details) {
        if(!compact && bottom-result.form_top>=154+minimum_form) {
            result.log_height=154;result.log_top=output_top-result.log_height;
            result.form_bottom-=result.log_height;
        }else {
            result.log_replaces_form=true;result.log_top=result.form_top;
            result.log_height=bottom-result.form_top;
        }
    }
    return result;
}
// END PORTABLE WORKFLOW GEOMETRY

// Native Shell pickers keep ordinary filesystem paths in the UI and argument list.
std::wstring choose_path(HWND parent, const std::wstring& type, const std::wstring& filter,
    const std::wstring& current, const std::wstring& title) {
    IFileOpenDialog* dialog=nullptr;
    HRESULT hr=CoCreateInstance(CLSID_FileOpenDialog,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&dialog));
    if(FAILED(hr)) throw std::runtime_error("The Windows file picker could not be opened.");
    struct Release { IFileOpenDialog* p; ~Release(){p->Release();} } release{dialog};
    FILEOPENDIALOGOPTIONS options{}; hr=dialog->GetOptions(&options);
    if(SUCCEEDED(hr)) hr=dialog->SetOptions(options|FOS_FORCEFILESYSTEM|FOS_PATHMUSTEXIST|FOS_NOCHANGEDIR|
        (type==L"directory" ? FOS_PICKFOLDERS:FOS_FILEMUSTEXIST)|(type==L"files"?FOS_ALLOWMULTISELECT:0));
    if(FAILED(hr)) throw std::runtime_error("The Windows file picker could not be configured.");
    dialog->SetTitle(title.c_str());
    std::vector<std::wstring> filter_parts;
    if(type!=L"directory") {
        size_t at=0;
        while(at<=filter.size()) { size_t end=filter.find(L'|',at); filter_parts.push_back(filter.substr(at,end==std::wstring::npos?end:end-at)); if(end==std::wstring::npos)break; at=end+1; }
        if(filter_parts.size()<2 || filter_parts.size()%2) filter_parts={L"All files",L"*.*"};
        std::vector<COMDLG_FILTERSPEC> specs;
        for(size_t i=0;i+1<filter_parts.size();i+=2) specs.push_back({filter_parts[i].c_str(),filter_parts[i+1].c_str()});
        dialog->SetFileTypes(static_cast<UINT>(specs.size()),specs.data());
    }
    std::wstring initial=current.substr(0,current.find_first_of(L"\r\n"));
    if(type!=L"directory" || !bw::directory_exists(initial)) {
        auto slash=initial.find_last_of(L"\\/"); if(slash!=std::wstring::npos)initial.resize(slash);else initial.clear();
    }
    if(!initial.empty()) {
        IShellItem* item=nullptr;
        if(SUCCEEDED(SHCreateItemFromParsingName(initial.c_str(),nullptr,IID_PPV_ARGS(&item)))) { dialog->SetFolder(item);item->Release(); }
    }
    hr=dialog->Show(parent); if(hr==HRESULT_FROM_WIN32(ERROR_CANCELLED))return {};
    if(FAILED(hr))throw std::runtime_error("The Windows file picker failed.");
    IShellItemArray* items=nullptr; hr=dialog->GetResults(&items);
    if(FAILED(hr))throw std::runtime_error("The selected paths could not be read.");
    struct ReleaseItems {IShellItemArray* p;~ReleaseItems(){p->Release();}} release_items{items};
    DWORD count=0; items->GetCount(&count); std::wstring result;
    for(DWORD i=0;i<count;++i) {
        IShellItem* item=nullptr; hr=items->GetItemAt(i,&item);
        if(FAILED(hr))throw std::runtime_error("A selected path could not be read.");
        PWSTR path=nullptr; hr=item->GetDisplayName(SIGDN_FILESYSPATH,&path);item->Release();
        if(FAILED(hr))throw std::runtime_error("Select a file or folder on a local filesystem.");
        if(!result.empty())result+=L"\r\n"; result+=path;CoTaskMemFree(path);
    }
    return result;
}

class Application {
public:
    HINSTANCE instance{}; HWND window{}; bool auto_check=false;
    ~Application() {
        cancel.store(true); if(worker.joinable())worker.join();
        for(HFONT f:{font,small_font,title_font,pack_font,log_font,semibold_font})if(f)DeleteObject(f);
        for(HBRUSH b:{canvas_brush,paper_brush,sidebar_brush})if(b)DeleteObject(b);
    }
    static LRESULT CALLBACK procedure(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp) {
        auto* app=reinterpret_cast<Application*>(GetWindowLongPtrW(hwnd,GWLP_USERDATA));
        if(msg==WM_NCCREATE) { app=static_cast<Application*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);app->window=hwnd;SetWindowLongPtrW(hwnd,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(app)); }
        if(!app)return DefWindowProcW(hwnd,msg,wp,lp);
        try{return app->handle(msg,wp,lp);}
        catch(const std::exception& e){app->show_error(exception_message(e));return msg==WM_CREATE?-1:0;}
        catch(...){app->show_error(L"An unexpected error occurred. Please close and reopen Native Workbench.");return msg==WM_CREATE?-1:0;}
    }
    static LRESULT CALLBACK child_procedure(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp) {
        auto* app=reinterpret_cast<Application*>(GetWindowLongPtrW(hwnd,GWLP_USERDATA));
        if(msg==WM_NCCREATE){app=static_cast<Application*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);SetWindowLongPtrW(hwnd,GWLP_USERDATA,reinterpret_cast<LONG_PTR>(app));}
        if(!app)return DefWindowProcW(hwnd,msg,wp,lp);
        try {
            const int id=GetDlgCtrlID(hwnd);
            if(id==ID_WHEEL)return app->wheel_message(hwnd,msg,wp,lp);
            if(msg==WM_PAINT){app->paint_form();return 0;}
            if(msg==WM_ERASEBKGND){RECT r{};GetClientRect(hwnd,&r);FillRect(reinterpret_cast<HDC>(wp),&r,app->paper_brush);return 1;}
            if(msg==WM_VSCROLL){app->scroll_form(LOWORD(wp));return 0;}
            if(msg==WM_MOUSEWHEEL){app->scroll_by(-GET_WHEEL_DELTA_WPARAM(wp)*54/WHEEL_DELTA);return 0;}
            if(msg==WM_COMMAND || msg==WM_DRAWITEM || msg==WM_CTLCOLOREDIT || msg==WM_CTLCOLORSTATIC || msg==WM_CTLCOLORBTN)
                return SendMessageW(app->window,msg,wp,lp);
        }catch(const std::exception& e){app->show_error(exception_message(e));return 0;}
        return DefWindowProcW(hwnd,msg,wp,lp);
    }
    static LRESULT CALLBACK workspace_subclass(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp,UINT_PTR,DWORD_PTR data) {
        auto* app=reinterpret_cast<Application*>(data);
        if(msg==WM_SETFOCUS){app->ensure_workspace_visible(hwnd);app->invalidate_field_border(hwnd);}
        if(msg==WM_KILLFOCUS)app->invalidate_field_border(hwnd);
        if(msg==WM_NCDESTROY)RemoveWindowSubclass(hwnd,workspace_subclass,2);
        return DefSubclassProc(hwnd,msg,wp,lp);
    }
    static LRESULT CALLBACK field_subclass(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp,UINT_PTR,DWORD_PTR data) {
        auto* app=reinterpret_cast<Application*>(data);
        if(msg==WM_SETFOCUS){app->ensure_visible(hwnd);app->ensure_workspace_visible(hwnd);app->invalidate_field_border(hwnd);}
        if(msg==WM_KILLFOCUS)app->invalidate_field_border(hwnd);
        if(msg==WM_MOUSEWHEEL && !SendMessageW(hwnd,CB_GETDROPPEDSTATE,0,0)) {
            // Multiline edits keep their own scrolling; other fields scroll the form.
            wchar_t klass[32]{};GetClassNameW(hwnd,klass,32);
            if(std::wcscmp(klass,L"Edit")!=0 || !(GetWindowLongPtrW(hwnd,GWL_STYLE)&ES_MULTILINE)) {
                app->scroll_by(-GET_WHEEL_DELTA_WPARAM(wp)*54/WHEEL_DELTA);return 0;
            }
        }
        if(msg==WM_NCDESTROY)RemoveWindowSubclass(hwnd,field_subclass,1);
        return DefSubclassProc(hwnd,msg,wp,lp);
    }
private:
    struct Field {bw::Input input;HWND label{},value{},browse{},help{};int y=0,height=0,label_h=0,help_h=0,value_y=0,value_h=0;};
    struct Placement {HWND window;int x,y,width,height;};
    std::vector<Placement> placements;
    HWND wheel{},pack_name{},pack_version{},pack_description{},wheel_hint{},pack_label{},pack_combo{},prev_button{},next_button{},add_pack{},check_button{},local_label{};
    HWND title{},subtitle{},workflow_label{},workflow_combo{},description{},steps_label{},outputs_label{},inputs_label{},form{};
    HWND output_label{},output_edit{},output_pick{},output_note{},run_button{},cancel_button{},open_button{},details_button{},status{},elapsed{},progress{},log_edit{},footer{};
    std::vector<HWND> controls;std::vector<Field> fields;std::vector<bw::Pack> packs;std::vector<int> pack_choices;
    std::map<std::wstring,std::map<std::wstring,std::wstring>> saved_values;
    std::wstring root,result_folder;
    HFONT font{},small_font{},title_font{},pack_font{},log_font{},semibold_font{};
    HBRUSH canvas_brush=CreateSolidBrush(CANVAS),paper_brush=CreateSolidBrush(PAPER),sidebar_brush=CreateSolidBrush(SIDEBAR);
    UINT dpi=96;int selected=-1,selected_workflow=-1,form_scroll=0,form_height=0,form_width=0,form_content=0;
    int width=1180,height=820,main_x=302,main_width=850,form_top=284,output_top=610,form_bottom=578;
    int sidebar_width=280,wheel_size=270,form_card_top=279,sidebar_card_top=344,detail_height=0;
    bool compact=false,metadata_in_form=false,log_replaces_form=false;
    bool wheel_keyboard_focus=false,wheel_pointer_focus=false;
    int form_inner_width=0;
    int viewport_width=800,viewport_height=480,workspace_x=0,workspace_y=0;
    bool layout_active=false;
    bool combo_refresh=false,busy=false,pending_close=false,show_details=false,dragging=false,drag_moved=false;
    double drag_angle=0;int drag_selection=-1;
    bw::Cancel cancel{false};std::thread worker;ULONGLONG started=0,elapsed_ms=0;int outcome=0;
    int px(int n)const{return MulDiv(n,static_cast<int>(dpi),96);}
    COLORREF accent()const{return selected>=0&&static_cast<size_t>(selected)<packs.size()?colorref(packs[selected].color):RGB(44,104,113);}
    HWND make(const wchar_t* klass,const wchar_t* text,DWORD style,int id=0,DWORD extended=0,HWND parent=nullptr) {
        HWND h=CreateWindowExW(extended,klass,text,WS_CHILD|WS_VISIBLE|WS_CLIPSIBLINGS|style,0,0,1,1,parent?parent:window,
            reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),instance,nullptr);
        if(!h)throw std::runtime_error("A desktop control could not be created.");
        controls.push_back(h);if(font)SendMessageW(h,WM_SETFONT,reinterpret_cast<WPARAM>(font),TRUE);
        if(std::wcscmp(klass,L"EDIT")==0)SendMessageW(h,EM_SETMARGINS,EC_LEFTMARGIN|EC_RIGHTMARGIN,MAKELPARAM(2,2));
        if(std::wcscmp(klass,L"COMBOBOX")==0)SetWindowTheme(h,L"Explorer",nullptr);
        if((style&WS_TABSTOP)&&GetParent(h)==window)SetWindowSubclass(h,workspace_subclass,2,reinterpret_cast<DWORD_PTR>(this));
        return h;
    }
    HWND label(const wchar_t* text,HWND parent=nullptr){return make(L"STATIC",text,SS_LEFT|SS_NOPREFIX|SS_EDITCONTROL,0,0,parent);}
    HWND button(const wchar_t* text,int id,HWND parent=nullptr){return make(L"BUTTON",text,WS_TABSTOP|BS_OWNERDRAW,id,0,parent);}
    HWND edit(int id,HWND parent=nullptr,bool multiple=false){return make(L"EDIT",L"",WS_TABSTOP|(multiple?ES_MULTILINE|ES_AUTOVSCROLL|ES_WANTRETURN|WS_VSCROLL:ES_AUTOHSCROLL),id,0,parent);}
    HWND combo(int id,HWND parent=nullptr,bool search=false){return make(L"COMBOBOX",L"",WS_TABSTOP|WS_VSCROLL|(search?CBS_DROPDOWN|CBS_AUTOHSCROLL:CBS_DROPDOWNLIST),id,0,parent);}
    void place(HWND h,int x,int y,int w,int hgt){
        if(!h)return;
        if(GetParent(h)==window){x-=workspace_x;y-=workspace_y;}
        placements.push_back({h,px(x),px(y),px(std::max(1,w)),px(std::max(1,hgt))});
    }
    void scroll_workspace(bool horizontal,int amount) {
        int& position=horizontal?workspace_x:workspace_y;
        const int maximum=horizontal?std::max(0,width-viewport_width):std::max(0,height-viewport_height);
        int next=std::clamp(position+amount,0,maximum);
        if(next!=position){position=next;layout();}
    }
    void workspace_scroll_command(bool horizontal,int action) {
        SCROLLINFO info{};info.cbSize=sizeof(info);info.fMask=SIF_TRACKPOS;
        GetScrollInfo(window,horizontal?SB_HORZ:SB_VERT,&info);
        const int page=std::max(1,(horizontal?viewport_width:viewport_height)-36);
        const int position=horizontal?workspace_x:workspace_y;
        const int extent=horizontal?width:height;
        switch(action){case SB_LINEUP:scroll_workspace(horizontal,-36);break;case SB_LINEDOWN:scroll_workspace(horizontal,36);break;
        case SB_PAGEUP:scroll_workspace(horizontal,-page);break;case SB_PAGEDOWN:scroll_workspace(horizontal,page);break;
        case SB_THUMBTRACK:case SB_THUMBPOSITION:scroll_workspace(horizontal,info.nTrackPos-position);break;
        case SB_TOP:scroll_workspace(horizontal,-extent);break;case SB_BOTTOM:scroll_workspace(horizontal,extent);break;}
    }
    void ensure_workspace_visible(HWND control) {
        if(layout_active || (width<=viewport_width&&height<=viewport_height))return;
        RECT r{},client{};GetWindowRect(control,&r);MapWindowPoints(nullptr,window,reinterpret_cast<POINT*>(&r),2);GetClientRect(window,&client);
        int dx=0,dy=0;
        if(r.left<0 || r.right-r.left>client.right)dx=r.left-px(8);
        else if(r.right>client.right)dx=r.right-client.right+px(8);
        if(r.top<0 || r.bottom-r.top>client.bottom)dy=r.top-px(8);
        else if(r.bottom>client.bottom)dy=r.bottom-client.bottom+px(8);
        auto logical_delta=[this](int value){return value<0?-static_cast<int>((static_cast<long long>(-value)*96+dpi-1)/dpi):static_cast<int>((static_cast<long long>(value)*96+dpi-1)/dpi);};
        const int x=std::clamp(workspace_x+logical_delta(dx),0,std::max(0,width-viewport_width));
        const int y=std::clamp(workspace_y+logical_delta(dy),0,std::max(0,height-viewport_height));
        if(x!=workspace_x||y!=workspace_y){workspace_x=x;workspace_y=y;layout();}
    }
    void apply_positions() {
        // No bitmap copying or intermediate painting while old/new child rectangles
        // overlap. Repaint the complete clipped subtree only after all moves finish.
        const UINT flags=SWP_NOZORDER|SWP_NOACTIVATE|SWP_NOREDRAW|SWP_NOCOPYBITS;
        HDWP batch=BeginDeferWindowPos(static_cast<int>(placements.size()));
        if(batch)for(const auto& p:placements){batch=DeferWindowPos(batch,p.window,nullptr,p.x,p.y,p.width,p.height,flags);if(!batch)break;}
        const bool applied=batch && EndDeferWindowPos(batch);
        if(!applied)for(const auto& p:placements)SetWindowPos(p.window,nullptr,p.x,p.y,p.width,p.height,flags);
        placements.clear();
    }
    int text_height(const std::wstring& text,HFONT face,int logical_width)const {
        if(text.empty())return 0;
        HDC dc=GetDC(window);HGDIOBJ previous=SelectObject(dc,face);
        RECT bounds{0,0,px(std::max(1,logical_width)),0};
        DrawTextW(dc,text.c_str(),static_cast<int>(text.size()),&bounds,DT_CALCRECT|DT_WORDBREAK|DT_EDITCONTROL|DT_NOPREFIX);
        SelectObject(dc,previous);ReleaseDC(window,dc);
        // Round up rather than down at 125/150% DPI and leave a physical-pixel guard.
        return static_cast<int>((static_cast<long long>(bounds.bottom+1)*96+dpi-1)/dpi)+1;
    }
    void metadata_parent(HWND parent) {
        for(HWND h:{description,steps_label,outputs_label})if(GetParent(h)!=parent){ShowWindow(h,SW_HIDE);SetParent(h,parent);}
    }
    void set_fonts() {
        auto create=[&](int points,int weight,const wchar_t* face){return CreateFontW(-MulDiv(points,static_cast<int>(dpi),72),0,0,0,weight,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH,face);};
        HFONT next=create(10,FW_NORMAL,L"Segoe UI"),small=create(9,FW_NORMAL,L"Segoe UI"),heading=create(23,FW_SEMIBOLD,L"Segoe UI"),pack=create(17,FW_SEMIBOLD,L"Segoe UI"),mono=create(9,FW_NORMAL,L"Consolas"),bold=create(10,FW_SEMIBOLD,L"Segoe UI");
        for(HWND h:controls)if(IsWindow(h))SendMessageW(h,WM_SETFONT,reinterpret_cast<WPARAM>(next),TRUE);
        for(HWND h:{subtitle,description,steps_label,outputs_label,output_note,wheel_hint,pack_version,pack_description,footer,local_label,elapsed})if(h)SendMessageW(h,WM_SETFONT,reinterpret_cast<WPARAM>(small),TRUE);
        for(HWND h:{workflow_label,inputs_label,output_label,pack_label,run_button,status})if(h)SendMessageW(h,WM_SETFONT,reinterpret_cast<WPARAM>(bold),TRUE);
        if(title)SendMessageW(title,WM_SETFONT,reinterpret_cast<WPARAM>(heading),TRUE);
        if(pack_name)SendMessageW(pack_name,WM_SETFONT,reinterpret_cast<WPARAM>(pack),TRUE);
        if(log_edit)SendMessageW(log_edit,WM_SETFONT,reinterpret_cast<WPARAM>(mono),TRUE);
        for(auto& f:fields){SendMessageW(f.label,WM_SETFONT,reinterpret_cast<WPARAM>(bold),TRUE);if(f.help)SendMessageW(f.help,WM_SETFONT,reinterpret_cast<WPARAM>(small),TRUE);}
        for(HFONT f:{font,small_font,title_font,pack_font,log_font,semibold_font})if(f)DeleteObject(f);
        font=next;small_font=small;title_font=heading;pack_font=pack;log_font=mono;semibold_font=bold;
    }
    void create_controls() {
        using DpiFn=UINT(WINAPI*)(HWND);
        auto getdpi=reinterpret_cast<DpiFn>(GetProcAddress(GetModuleHandleW(L"user32.dll"),"GetDpiForWindow"));if(getdpi)dpi=getdpi(window);
        wheel=CreateWindowExW(0,L"NativeWorkbenchSurface040",L"Pack wheel. Use arrow keys, turn the mouse wheel, or drag to change pack.",WS_CHILD|WS_VISIBLE|WS_TABSTOP|WS_CLIPSIBLINGS,0,0,1,1,window,reinterpret_cast<HMENU>(ID_WHEEL),instance,this);
        if(!wheel)throw std::runtime_error("The pack wheel could not be created.");
        SetWindowSubclass(wheel,workspace_subclass,2,reinterpret_cast<DWORD_PTR>(this));
        wheel_hint=label(L"Turn the wheel to explore your packs");
        prev_button=button(L"\x2039  Previous",ID_PREV);next_button=button(L"Next  \x203A",ID_NEXT);
        pack_name=label(L"Your workbench");pack_version=label(L"LOCAL TOOL PACKS");pack_description=label(L"Load a pack to get started. Its inputs, tools and workflows appear here.");
        pack_label=label(L"Find a pack");pack_combo=combo(ID_PACK,nullptr,true);
        SendMessageW(pack_combo,CB_SETMINVISIBLE,8,0);
        add_pack=button(L"+  Install pack",ID_ADD_PACK);check_button=button(L"Check installation",ID_CHECK);
        local_label=label(L"\x25CF  Processing stays on this computer");
        title=label(L"Native Workbench");subtitle=label(L"Your data. Your computer. Your workspace.");
        workflow_label=label(L"WORKFLOW");workflow_combo=combo(ID_WORKFLOW);description=label(L"");steps_label=label(L"");outputs_label=label(L"");inputs_label=label(L"Inputs & options");
        form=CreateWindowExW(WS_EX_CONTROLPARENT,L"NativeWorkbenchSurface040",L"Workflow inputs",WS_CHILD|WS_VISIBLE|WS_VSCROLL|WS_CLIPCHILDREN|WS_CLIPSIBLINGS,0,0,1,1,window,reinterpret_cast<HMENU>(ID_FORM),instance,this);
        if(!form)throw std::runtime_error("The input form could not be created.");
        output_label=label(L"SAVE RESULTS TO");output_edit=edit(ID_OUTPUT);output_pick=button(L"Browse\x2026",ID_PICK_OUTPUT);output_note=label(L"Every run gets a new folder. Previous results are kept.");
        run_button=button(L"Run workflow   \x2192",ID_RUN);cancel_button=button(L"Cancel",ID_CANCEL);open_button=button(L"Open results",ID_OPEN_RESULTS);details_button=button(L"Show details  \x2304",ID_DETAILS);
        status=label(L"Loading installed packs\x2026");elapsed=make(L"STATIC",L"",SS_RIGHT|SS_NOPREFIX);
        progress=make(PROGRESS_CLASSW,L"",PBS_MARQUEE);SendMessageW(progress,PBM_SETBARCOLOR,0,accent());
        log_edit=make(L"EDIT",L"",WS_TABSTOP|WS_VSCROLL|ES_MULTILINE|ES_READONLY|ES_AUTOVSCROLL,0,0);
        SendMessageW(log_edit,EM_SETLIMITTEXT,400000,0);
        footer=label((L"NATIVE WORKBENCH "+std::wstring(bw::APP_VERSION)+L"  /  LOCAL FIRST").c_str());
        root=bw::executable_folder();const auto output=bw::join(root,L"results");
        if(!bw::directory_exists(output)&&!CreateDirectoryW(bw::native_path(output).c_str(),nullptr))append_log(L"The default results folder could not be created. Choose a writable output folder.");
        SetWindowTextW(output_edit,output.c_str());
        set_fonts();layout();update_enabled();SetTimer(window,TIMER_ELAPSED,250,nullptr);PostMessageW(window,MSG_INITIALIZE,0,0);
        // Windows 11 can round the top-level frame; Windows 10 ignores the hint.
        HMODULE dwm=LoadLibraryW(L"dwmapi.dll");if(dwm){using DwmFn=HRESULT(WINAPI*)(HWND,DWORD,LPCVOID,DWORD);auto set=reinterpret_cast<DwmFn>(GetProcAddress(dwm,"DwmSetWindowAttribute"));if(set){DWORD rounded_corner=2;set(window,33,&rounded_corner,sizeof(rounded_corner));}FreeLibrary(dwm);}
    }
    void layout() {
        if(!title || !font || IsIconic(window) || layout_active)return;
        layout_active=true;struct LayoutGuard{bool& active;~LayoutGuard(){active=false;}} guard{layout_active};
        placements.clear();
        // A tiny logical viewport is possible at very high display scaling. Keep
        // the usable canvas and expose native outer scrollbars, including focus
        // following for keyboard users. Never squeeze the form into the footer.
        RECT rc{};GetClientRect(window,&rc);
        using MetricsFn=int(WINAPI*)(int,UINT);
        auto metrics=reinterpret_cast<MetricsFn>(GetProcAddress(GetModuleHandleW(L"user32.dll"),"GetSystemMetricsForDpi"));
        const int vertical_bar=metrics?metrics(SM_CXVSCROLL,dpi):GetSystemMetrics(SM_CXVSCROLL);
        const int horizontal_bar=metrics?metrics(SM_CYHSCROLL,dpi):GetSystemMetrics(SM_CYHSCROLL);
        const LONG_PTR style=GetWindowLongPtrW(window,GWL_STYLE);
        // Recover the area before existing bars were subtracted. Otherwise a pair
        // of old bars can keep each other visible at the exact fit threshold.
        const int base_width=rc.right+((style&WS_VSCROLL)?vertical_bar:0);
        const int base_height=rc.bottom+((style&WS_HSCROLL)?horizontal_bar:0);
        bool horizontal_needed=false,vertical_needed=false;
        for(int pass=0;pass<3;++pass) {
            const int available_width=base_width-(vertical_needed?vertical_bar:0);
            const int available_height=base_height-(horizontal_needed?horizontal_bar:0);
            const bool next_horizontal=static_cast<long long>(available_width)*96/dpi<MIN_WORKSPACE_WIDTH;
            const bool next_vertical=static_cast<long long>(available_height)*96/dpi<MIN_WORKSPACE_HEIGHT;
            if(next_horizontal==horizontal_needed&&next_vertical==vertical_needed)break;
            horizontal_needed=next_horizontal;vertical_needed=next_vertical;
        }
        ShowScrollBar(window,SB_HORZ,horizontal_needed);ShowScrollBar(window,SB_VERT,vertical_needed);
        GetClientRect(window,&rc);
        viewport_width=std::max(1,static_cast<int>(static_cast<long long>(rc.right)*96/dpi));
        viewport_height=std::max(1,static_cast<int>(static_cast<long long>(rc.bottom)*96/dpi));
        width=std::max(MIN_WORKSPACE_WIDTH,viewport_width);height=std::max(MIN_WORKSPACE_HEIGHT,viewport_height);
        workspace_x=std::clamp(workspace_x,0,width-viewport_width);workspace_y=std::clamp(workspace_y,0,height-viewport_height);
        SCROLLINFO horizontal{};horizontal.cbSize=sizeof(horizontal);horizontal.fMask=SIF_RANGE|SIF_PAGE|SIF_POS;
        horizontal.nMax=width-1;horizontal.nPage=static_cast<UINT>(viewport_width);horizontal.nPos=workspace_x;SetScrollInfo(window,SB_HORZ,&horizontal,FALSE);
        SCROLLINFO vertical{};vertical.cbSize=sizeof(vertical);vertical.fMask=SIF_RANGE|SIF_PAGE|SIF_POS;
        vertical.nMax=height-1;vertical.nPage=static_cast<UINT>(viewport_height);vertical.nPos=workspace_y;SetScrollInfo(window,SB_VERT,&vertical,FALSE);
        compact=height<790;sidebar_width=width<1050?220:280;main_x=sidebar_width+22;main_width=std::max(340,width-main_x-28);
        const double side_scale=compact?std::clamp(height/820.0,0.60,1.0):1.0;
        wheel_size=std::min(sidebar_width-10,static_cast<int>(270*side_scale));
        const int side_inner=sidebar_width-48,nav_width=(side_inner-10)/2;
        place(wheel,0,0,wheel_size,wheel_size);place(wheel_hint,24,271,side_inner,20);ShowWindow(wheel_hint,compact?SW_HIDE:SW_SHOW);
        place(prev_button,24,static_cast<int>(301*side_scale),nav_width,32);place(next_button,34+nav_width,static_cast<int>(301*side_scale),nav_width,32);
        sidebar_card_top=static_cast<int>(344*side_scale);
        place(pack_name,24,sidebar_card_top+15,side_inner,58);place(pack_version,25,sidebar_card_top+81,side_inner-3,20);
        place(pack_description,25,459,side_inner-3,66);ShowWindow(pack_description,compact?SW_HIDE:SW_SHOW);
        const int pack_select_y=compact?std::min(sidebar_card_top+157,height-169):566;
        place(pack_label,24,pack_select_y-25,side_inner,22);ShowWindow(pack_label,height<530?SW_HIDE:SW_SHOW);place(pack_combo,24,pack_select_y,side_inner,230);
        place(add_pack,24,height-(compact?125:158),side_inner,36);place(check_button,24,height-(compact?80:113),side_inner,36);
        place(local_label,25,height-(compact?30:57),side_inner,19);
        place(title,main_x,compact?16:27,main_width-10,39);place(subtitle,main_x+1,compact?64:76,main_width-2,23);ShowWindow(subtitle,height<660?SW_HIDE:SW_SHOW);
        const int header_shift=height<660?35:0;
        const int workflow_y=compact?101-header_shift:118;
        const int workflow_label_height=text_height(L"WORKFLOW",semibold_font,main_width);
        const int combo_y=workflow_y+workflow_label_height+6;
        const int combo_height=std::max(32,text_height(L"Mg",font,main_width)+12);
        const int text_top=combo_y+combo_height+10;
        place(workflow_label,main_x,workflow_y,main_width,workflow_label_height);
        place(workflow_combo,main_x,combo_y,main_width,240);
        output_top=height-227;
        const int description_height=text_height(control_text(description),small_font,main_width-3);
        const int steps_height=text_height(control_text(steps_label),small_font,main_width-3);
        const int outputs_height=text_height(control_text(outputs_label),small_font,main_width-3);
        const auto geometry=workflow_geometry(text_top,output_top,description_height,steps_height,outputs_height,compact,show_details);
        metadata_in_form=geometry.metadata_in_form;log_replaces_form=geometry.log_replaces_form;
        metadata_parent(metadata_in_form?form:window);
        if(!metadata_in_form) {
            place(description,main_x+1,geometry.description_y,main_width-3,description_height);
            place(steps_label,main_x+1,geometry.steps_y,main_width-3,steps_height);
            place(outputs_label,main_x+1,geometry.outputs_y,main_width-3,outputs_height);
            ShowWindow(description,description_height?SW_SHOW:SW_HIDE);
            ShowWindow(steps_label,geometry.summaries&&steps_height?SW_SHOW:SW_HIDE);
            ShowWindow(outputs_label,geometry.summaries&&outputs_height?SW_SHOW:SW_HIDE);
        }
        form_card_top=geometry.card_top;form_top=geometry.form_top;form_bottom=geometry.form_bottom;
        SetWindowTextW(inputs_label,log_replaces_form?L"Run details":metadata_in_form?L"Workflow information & inputs":L"Inputs & options");
        place(inputs_label,main_x+18,form_card_top+14,main_width-36,24);
        detail_height=show_details&&!log_replaces_form?geometry.log_height:0;
        form_height=std::max(1,form_bottom-form_top);form_width=main_width-28;
        place(form,main_x+14,form_top,form_width,form_height);
        if(log_replaces_form&&IsChild(form,GetFocus()))SetFocus(details_button);
        ShowWindow(form,log_replaces_form?SW_HIDE:SW_SHOW);
        if(log_replaces_form)place(log_edit,main_x+15,form_top+3,main_width-30,form_height-6);
        else place(log_edit,main_x+15,geometry.log_top+7,main_width-30,std::max(35,detail_height-22));
        ShowWindow(log_edit,show_details?SW_SHOW:SW_HIDE);
        place(output_label,main_x,output_top,main_width,20);
        place(output_edit,main_x+12,output_top+34,main_width-126,24);place(output_pick,main_x+main_width-96,output_top+27,96,37);
        place(output_note,main_x+1,output_top+72,main_width-2,text_height(control_text(output_note),small_font,main_width-2));
        const int actions=height-116,run_width=std::clamp(main_width/4,124,184),cancel_width=main_width<500?60:75;
        const int open_width=main_width<500?84:120,details_width=main_width<500?103:140,gap=main_width<500?7:11;
        place(run_button,main_x,actions,run_width,43);place(cancel_button,main_x+run_width+gap,actions,cancel_width,43);
        place(open_button,main_x+run_width+cancel_width+gap*2,actions,open_width,43);place(details_button,main_x+main_width-details_width,actions,details_width,43);
        place(status,main_x+1,height-58,main_width-152,23);place(elapsed,main_x+main_width-146,height-58,146,23);
        place(progress,main_x,height-26,main_width,4);ShowWindow(progress,busy?SW_SHOW:SW_HIDE);
        place(footer,main_x,height-22,main_width,18);ShowWindow(footer,busy?SW_HIDE:SW_SHOW);
        apply_positions();layout_fields(false);
        RedrawWindow(window,nullptr,nullptr,RDW_INVALIDATE|RDW_ERASE|RDW_ALLCHILDREN|RDW_FRAME);
    }
    const bw::Workflow* workflow()const {
        if(selected<0||static_cast<size_t>(selected)>=packs.size())return nullptr;
        const auto& list=packs[selected].workflows;
        return selected_workflow>=0&&static_cast<size_t>(selected_workflow)<list.size()?&list[selected_workflow]:nullptr;
    }
    std::wstring value_key()const {const auto* wf=workflow();return wf?packs[selected].id+L"@"+packs[selected].version+L"/"+wf->id:L"";}
    std::map<std::wstring,std::wstring> field_values()const {
        std::map<std::wstring,std::wstring> values;
        for(const auto& field:fields) {
            std::wstring value;
            if(field.input.type==L"boolean")value=SendMessageW(field.value,BM_GETCHECK,0,0)==BST_CHECKED?L"true":L"false";
            else if(field.input.type==L"choice") {int index=static_cast<int>(SendMessageW(field.value,CB_GETCURSEL,0,0));if(index>=0&&static_cast<size_t>(index)<field.input.choices.size())value=field.input.choices[index].value;}
            else value=lines_to_lf(control_text(field.value));
            values[field.input.id]=std::move(value);
        }
        return values;
    }
    void save_fields(){auto key=value_key();if(!key.empty())saved_values[key]=field_values();}
    void clear_fields(){for(auto& f:fields)for(HWND h:{f.label,f.value,f.browse,f.help})if(h){controls.erase(std::remove(controls.begin(),controls.end(),h),controls.end());DestroyWindow(h);}fields.clear();}
    void rebuild_fields() {
        clear_fields();form_scroll=0;const auto* wf=workflow();
        if(!wf){SetWindowTextW(description,L"Choose an installed tool pack to view its workflows.");SetWindowTextW(steps_label,L"");SetWindowTextW(outputs_label,L"");layout();return;}
        SetWindowTextW(description,wf->description.c_str());
        std::wstring step_text=std::to_wstring(wf->steps.size())+(wf->steps.size()==1?L" step":L" steps");
        for(const auto& step:wf->steps){step_text+=L"  \x203A  "+step.label;if(step_text.size()>180){step_text+=L"\x2026";break;}}
        SetWindowTextW(steps_label,step_text.c_str());std::wstring output_text=L"Creates: ";bool first=true;
        for(const auto& out:wf->outputs)if(out.final){if(!first)output_text+=L"  \x2022  ";output_text+=out.label;first=false;}
        if(first)output_text=L"Each run saves its report and tool logs.";
        SetWindowTextW(outputs_label,output_text.c_str());
        const auto saved=saved_values.find(value_key());
        for(size_t i=0;i<wf->inputs.size();++i) {
            Field field;field.input=wf->inputs[i];const auto& input=field.input;const int id=ID_FIELD+static_cast<int>(i)*3;
            const std::wstring caption=input.label+(input.required?L"":L"  (optional)");field.label=label(caption.c_str(),form);
            std::wstring value=input.default_value;if(saved!=saved_values.end()){auto found=saved->second.find(input.id);if(found!=saved->second.end())value=found->second;}
            if(input.type==L"boolean") {
                field.value=make(L"BUTTON",input.label.c_str(),WS_TABSTOP|BS_AUTOCHECKBOX|BS_MULTILINE,id,0,form);
                SendMessageW(field.value,BM_SETCHECK,value==L"true"||value==L"1"?BST_CHECKED:BST_UNCHECKED,0);ShowWindow(field.label,SW_HIDE);
            }else if(input.type==L"choice") {
                field.value=combo(id,form);int choice=0;
                for(size_t j=0;j<input.choices.size();++j){SendMessageW(field.value,CB_ADDSTRING,0,reinterpret_cast<LPARAM>(input.choices[j].label.c_str()));if(input.choices[j].value==value)choice=static_cast<int>(j);}
                if(!input.choices.empty())SendMessageW(field.value,CB_SETCURSEL,choice,0);
            }else {
                field.value=edit(id,form,input.type==L"files");SetWindowTextW(field.value,lines_to_crlf(value).c_str());
                SendMessageW(field.value,EM_SETLIMITTEXT,input.type==L"files"?1048576:32767,0);
            }
            if(input.type==L"file"||input.type==L"files"||input.type==L"directory")field.browse=button(L"Browse\x2026",id+1,form);
            if(!input.help.empty())field.help=label(input.help.c_str(),form);
            SendMessageW(field.label,WM_SETFONT,reinterpret_cast<WPARAM>(semibold_font),TRUE);
            if(field.help)SendMessageW(field.help,WM_SETFONT,reinterpret_cast<WPARAM>(small_font),TRUE);
            SetWindowSubclass(field.value,field_subclass,1,reinterpret_cast<DWORD_PTR>(this));
            if(field.browse)SetWindowSubclass(field.browse,field_subclass,1,reinterpret_cast<DWORD_PTR>(this));
            fields.push_back(std::move(field));
        }
        layout();update_enabled();
    }
    void layout_fields(bool repaint=true) {
        if(!form)return;
        RECT client{};GetClientRect(form,&client);
        form_height=std::max(1,MulDiv(client.bottom,96,static_cast<int>(dpi)));
        // Keep the scrollbar gutter stable: measured widths equal painted widths,
        // including when a workflow fits completely and scrolling is disabled.
        form_inner_width=std::max(24,static_cast<int>(static_cast<long long>(client.right)*96/dpi)-14);
        const int inner=form_inner_width;int y=12;
        placements.clear();
        if(metadata_in_form) {
            for(HWND h:{description,steps_label,outputs_label}) {
                const int hgt=text_height(control_text(h),small_font,inner-7);
                place(h,7,y-form_scroll,inner-7,hgt);ShowWindow(h,hgt?SW_SHOW:SW_HIDE);
                if(hgt)y+=hgt+10;
            }
            y+=8;
        }
        for(auto& field:fields) {
            field.y=y;const bool boolean=field.input.type==L"boolean";
            field.label_h=boolean?0:text_height(control_text(field.label),semibold_font,inner-7)+6;
            field.help_h=text_height(field.input.help,small_font,inner-7);
            field.value_h=boolean?std::max(32,text_height(field.input.label,font,inner-40)+8):field.input.type==L"files"?74:std::max(36,text_height(L"Mg",font,inner-25)+16);
            field.value_y=y+field.label_h;
            field.height=field.label_h+field.value_h+(field.help_h?field.help_h+7:0)+20;y+=field.height;
        }
        form_content=y;const int maximum=std::max(0,form_content-form_height);form_scroll=std::clamp(form_scroll,0,maximum);
        if(!repaint&&!log_replaces_form)for(const auto& field:fields)if(GetFocus()==field.value||GetFocus()==field.browse) {
            const int bottom=field.value_y+field.value_h+5;
            if(field.y<form_scroll)form_scroll=field.y;
            else if(bottom>form_scroll+form_height)form_scroll=bottom-form_height;
            form_scroll=std::clamp(form_scroll,0,maximum);break;
        }
        SCROLLINFO info{};info.cbSize=sizeof(info);info.fMask=SIF_RANGE|SIF_PAGE|SIF_POS|SIF_DISABLENOSCROLL;
        info.nMin=0;info.nMax=std::max(0,form_content-1);info.nPage=static_cast<UINT>(form_height);info.nPos=form_scroll;SetScrollInfo(form,SB_VERT,&info,FALSE);
        // The range can clamp after resize. Position metadata with the final offset.
        placements.clear();int metadata_y=12;
        if(metadata_in_form)for(HWND h:{description,steps_label,outputs_label}) {
            const int hgt=text_height(control_text(h),small_font,inner-7);
            place(h,7,metadata_y-form_scroll,inner-7,hgt);if(hgt)metadata_y+=hgt+10;
        }
        for(auto& field:fields) {
            const bool boolean=field.input.type==L"boolean",choice=field.input.type==L"choice";
            place(field.label,7,field.y-form_scroll,inner-7,std::max(1,field.label_h-6));
            const int edit_width=inner-(field.browse?104:0);
            if(boolean)place(field.value,8,field.value_y-form_scroll+2,inner-14,field.value_h-4);
            else if(choice)place(field.value,7,field.value_y-form_scroll+1,inner-7,240);
            else place(field.value,17,field.value_y-form_scroll+8,edit_width-25,field.value_h-15);
            if(field.browse)place(field.browse,inner-92,field.value_y-form_scroll,92,field.value_h==74?37:field.value_h);
            if(field.help)place(field.help,8,field.value_y+field.value_h+7-form_scroll,inner-7,field.help_h);
        }
        apply_positions();
        if(repaint)RedrawWindow(form,nullptr,nullptr,RDW_INVALIDATE|RDW_ERASE|RDW_ALLCHILDREN|RDW_FRAME|RDW_UPDATENOW);
    }
    void invalidate_field_border(HWND control) {
        if(control==output_edit) {
            RECT r{px(main_x-workspace_x-1),px(output_top+26-workspace_y),px(main_x+main_width-106-workspace_x),px(output_top+65-workspace_y)};
            InvalidateRect(window,&r,FALSE);return;
        }
        for(const auto& field:fields)if(field.value==control) {
            RECT r{px(6),px(field.value_y-form_scroll-1),px(form_inner_width),px(field.value_y-form_scroll+field.value_h+1)};
            InvalidateRect(form,&r,FALSE);return;
        }
    }
    void scroll_by(int amount){int next=std::clamp(form_scroll+amount,0,std::max(0,form_content-form_height));if(next!=form_scroll){form_scroll=next;layout_fields();}}
    void scroll_form(int action) {
        SCROLLINFO info{};info.cbSize=sizeof(info);info.fMask=SIF_TRACKPOS;GetScrollInfo(form,SB_VERT,&info);
        switch(action){case SB_LINEUP:scroll_by(-36);break;case SB_LINEDOWN:scroll_by(36);break;case SB_PAGEUP:scroll_by(-std::max(1,form_height-36));break;case SB_PAGEDOWN:scroll_by(std::max(1,form_height-36));break;case SB_THUMBTRACK:case SB_THUMBPOSITION:scroll_by(info.nTrackPos-form_scroll);break;case SB_TOP:scroll_by(-form_content);break;case SB_BOTTOM:scroll_by(form_content);break;}
    }
    void ensure_visible(HWND h) {
        for(const auto& f:fields)if(f.value==h||f.browse==h){int top=f.y,bottom=f.value_y+f.value_h+5;if(top<form_scroll)scroll_by(top-form_scroll);else if(bottom>form_scroll+form_height)scroll_by(bottom-form_scroll-form_height);break;}
    }
    void paint_form() {
        PAINTSTRUCT ps{};HDC dc=BeginPaint(form,&ps);RECT r{};GetClientRect(form,&r);
        if(r.right<=0||r.bottom<=0){EndPaint(form,&ps);return;}
        HDC buffer=CreateCompatibleDC(dc);HBITMAP bitmap=buffer?CreateCompatibleBitmap(dc,r.right,r.bottom):nullptr;
        HGDIOBJ previous=bitmap?SelectObject(buffer,bitmap):nullptr;
        HDC target=bitmap?buffer:dc;FillRect(target,&r,paper_brush);
        {
            Gdiplus::Graphics g(target);g.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
            g.SetClip(Gdiplus::Rect(0,0,r.right,r.bottom));g.ScaleTransform(dpi/96.0f,dpi/96.0f);
            const int inner=form_inner_width;
            for(const auto& f:fields) {
                if(f.input.type==L"boolean"||f.input.type==L"choice")continue;
                const int top=f.value_y-form_scroll;
                if(top+f.value_h<0||top>form_height)continue;
                const int w=inner-(f.browse?104:0)-7;const bool focus=GetFocus()==f.value;
                rounded(g,7.0f,static_cast<float>(top),static_cast<float>(w),static_cast<float>(f.value_h),8,PAPER,focus?accent():LINE);
            }
        }
        if(fields.empty()&&!metadata_in_form){SetTextColor(target,MUTED);SetBkMode(target,TRANSPARENT);HGDIOBJ old=SelectObject(target,font);RECT text{px(12),px(12),r.right-px(12),r.bottom};DrawTextW(target,L"This workflow needs no additional inputs.",-1,&text,DT_WORDBREAK|DT_NOPREFIX);SelectObject(target,old);}
        // BeginPaint's clip excludes native child windows and the scrollbar. The
        // buffered background/borders therefore cannot overpaint text or controls.
        if(bitmap){BitBlt(dc,0,0,r.right,r.bottom,buffer,0,0,SRCCOPY);SelectObject(buffer,previous);DeleteObject(bitmap);}
        if(buffer)DeleteDC(buffer);EndPaint(form,&ps);
    }
    void rebuild_pack_combo(const std::wstring& query=L"") {
        combo_refresh=true;SendMessageW(pack_combo,CB_RESETCONTENT,0,0);pack_choices.clear();const auto needle=lower(query);int current=-1;
        for(size_t i=0;i<packs.size();++i) {
            std::wstring hay=packs[i].name+L" "+packs[i].description;
            for(const auto& wf:packs[i].workflows)hay+=L" "+wf.name;
            if(!needle.empty()&&lower(hay).find(needle)==std::wstring::npos)continue;
            auto name=packs[i].name+L"  \x00B7  "+packs[i].version;
            SendMessageW(pack_combo,CB_ADDSTRING,0,reinterpret_cast<LPARAM>(name.c_str()));
            if(static_cast<int>(i)==selected)current=static_cast<int>(pack_choices.size());pack_choices.push_back(static_cast<int>(i));
        }
        if(query.empty()){if(current>=0)SendMessageW(pack_combo,CB_SETCURSEL,current,0);}
        else {SetWindowTextW(pack_combo,query.c_str());SendMessageW(pack_combo,CB_SETEDITSEL,0,MAKELPARAM(query.size(),query.size()));}
        combo_refresh=false;
    }
    void select_pack(int index,bool save=true) {
        if(busy||packs.empty())return;if(save)save_fields();
        selected=(index%static_cast<int>(packs.size())+static_cast<int>(packs.size()))%static_cast<int>(packs.size());selected_workflow=0;
        const auto& pack=packs[selected];SetWindowTextW(pack_name,pack.name.c_str());SetWindowTextW(pack_version,(L"VERSION "+pack.version).c_str());SetWindowTextW(pack_description,pack.description.c_str());
        SendMessageW(workflow_combo,CB_RESETCONTENT,0,0);
        for(const auto& wf:pack.workflows)SendMessageW(workflow_combo,CB_ADDSTRING,0,reinterpret_cast<LPARAM>(wf.name.c_str()));
        if(!pack.workflows.empty())SendMessageW(workflow_combo,CB_SETCURSEL,0,0);
        rebuild_pack_combo();rebuild_fields();InvalidateRect(window,nullptr,TRUE);InvalidateRect(wheel,nullptr,TRUE);update_enabled();
    }
    void refresh_packs(const std::wstring& prefer=L"") {
        save_fields();const std::wstring old=prefer.empty()&&selected>=0?packs[selected].root:prefer;
        packs=bw::discover_packs(root,[this](const std::wstring& line){append_log(line);});selected=-1;selected_workflow=-1;
        if(!packs.empty()){int index=0;for(size_t i=0;i<packs.size();++i)if(packs[i].root==old)index=static_cast<int>(i);select_pack(index,false);}
        else {rebuild_pack_combo();clear_fields();rebuild_fields();}
        SetWindowTextW(status,packs.empty()?L"Install a tool pack to get started.":L"Ready when you are.");update_enabled();
    }
    void update_enabled() {
        for(HWND h:{wheel,pack_combo,prev_button,next_button,add_pack,workflow_combo,output_edit,output_pick})EnableWindow(h,!busy);
        EnableWindow(prev_button,!busy&&packs.size()>1);EnableWindow(next_button,!busy&&packs.size()>1);
        for(const auto& f:fields){EnableWindow(f.value,!busy);if(f.browse)EnableWindow(f.browse,!busy);}
        EnableWindow(run_button,!busy&&workflow());EnableWindow(check_button,!busy&&!packs.empty());EnableWindow(cancel_button,busy&&!cancel.load());EnableWindow(open_button,!result_folder.empty());
        InvalidateRect(run_button,nullptr,TRUE);InvalidateRect(cancel_button,nullptr,TRUE);InvalidateRect(open_button,nullptr,TRUE);
    }
    void append_log(const std::wstring& line) {
        std::wstring text=lines_to_crlf(line);std::replace(text.begin(),text.end(),L'\0',L' ');
        if(text.size()>60000)text=L"[Long message truncated in this view]\r\n"+text.substr(text.size()-60000);
        if(text.size()<2||text.compare(text.size()-2,2,L"\r\n")!=0)text+=L"\r\n";
        int length=GetWindowTextLengthW(log_edit);if(length+static_cast<int>(text.size())>300000){SendMessageW(log_edit,EM_SETSEL,0,length-180000);SendMessageW(log_edit,EM_REPLACESEL,FALSE,reinterpret_cast<LPARAM>(L""));}
        SendMessageW(log_edit,EM_SETSEL,static_cast<WPARAM>(-1),static_cast<LPARAM>(-1));SendMessageW(log_edit,EM_REPLACESEL,FALSE,reinterpret_cast<LPARAM>(text.c_str()));SendMessageW(log_edit,EM_SCROLLCARET,0,0);
    }
    void show_error(const std::wstring& text){MessageBoxW(window,text.c_str(),L"Native Workbench",MB_OK|MB_ICONERROR);}
    void start_work(std::function<Completion(bw::Cancel&,const bw::Log&,const bw::Phase&)> task,const wchar_t* initial) {
        if(busy)return;if(worker.joinable())worker.join();cancel.store(false);busy=true;outcome=0;started=GetTickCount64();elapsed_ms=0;result_folder.clear();
        SetWindowTextW(log_edit,L"");SetWindowTextW(status,initial);SendMessageW(progress,PBM_SETMARQUEE,TRUE,35);ShowWindow(progress,SW_SHOW);ShowWindow(footer,SW_HIDE);update_enabled();update_elapsed();
        const HWND destination=window;
        try {worker=std::thread([this,destination,task=std::move(task)]()mutable {
            auto completion=std::make_unique<Completion>();
            try{const bw::Log log=[destination](const std::wstring& s){post_text(destination,MSG_LOG,s);};const bw::Phase phase=[destination](const std::wstring& s){post_text(destination,MSG_PHASE,s);};*completion=task(cancel,log,phase);}
            catch(const std::exception& e){completion->result.cancelled=cancel.load();completion->result.message=completion->result.cancelled?L"Cancelled.":exception_message(e);}
            catch(...){completion->result.cancelled=cancel.load();completion->result.message=L"The task stopped because of an unexpected error.";}
            while(IsWindow(destination)){if(PostMessageW(destination,MSG_COMPLETE,0,reinterpret_cast<LPARAM>(completion.get()))){completion.release();break;}Sleep(10);}
        });}catch(...){busy=false;SendMessageW(progress,PBM_SETMARQUEE,FALSE,0);update_enabled();layout();throw;}
    }
    void start_job() {
        if(busy)return;const auto* wf=workflow();if(!wf)throw std::runtime_error("Choose a workflow first.");
        save_fields();bw::WorkflowRequest request;request.pack=packs[selected];request.workflow_id=wf->id;request.values=field_values();request.output_folder=control_text(output_edit);
        if(!bw::directory_exists(request.output_folder))throw std::runtime_error("Choose an existing output folder.");
        for(const auto& field:fields) {
            const auto& value=request.values[field.input.id];
            if(field.input.required&&value.empty()){SetFocus(field.value);throw std::runtime_error(bw::utf8(L"Select or enter "+field.input.label+L" before running."));}
            if(field.input.type==L"integer"&&!value.empty()) {
                wchar_t* end=nullptr;errno=0;long long number=std::wcstoll(value.c_str(),&end,10);
                if(errno==ERANGE||end==value.c_str()||!end||*end||number<field.input.minimum||number>field.input.maximum){SetFocus(field.value);throw std::runtime_error(bw::utf8(field.input.label+L" must be a whole number from "+std::to_wstring(field.input.minimum)+L" to "+std::to_wstring(field.input.maximum)+L"."));}
            }
        }
        start_work([request](bw::Cancel& c,const bw::Log& l,const bw::Phase& p){Completion result;result.result=bw::run_workflow(request,c,l,p);return result;},L"Preparing your workflow\x2026");
    }
    void start_check() {
        if(busy)return;const auto output=control_text(output_edit),app_root=root;
        if(!bw::directory_exists(output))throw std::runtime_error("Choose an existing output folder for the installation report.");
        start_work([output,app_root](bw::Cancel& c,const bw::Log& l,const bw::Phase& p){Completion result;result.result=bw::validate_modular_installation(app_root,output,c,l,p);return result;},L"Checking your installation\x2026");
    }
    void add_pack_folder() {
        if(busy)return;const auto source=choose_path(window,L"directory",L"",root,L"Choose a tool pack folder containing pack.ini");if(source.empty())return;
        const auto question=L"Install this tool pack?\n\n"+source+L"\n\nPacks contain programs that run with your Windows account. Install packs only from a publisher you trust.";
        if(MessageBoxW(window,question.c_str(),L"Install a trusted pack",MB_YESNO|MB_ICONINFORMATION|MB_DEFBUTTON2)!=IDYES)return;
        const auto app_root=root;start_work([app_root,source](bw::Cancel& c,const bw::Log& l,const bw::Phase& p){p(L"Verifying and installing pack\x2026");Completion result;result.pack=bw::import_pack(app_root,source,c,l);result.imported=true;result.result.success=true;result.result.message=L"Installed "+result.pack.name+L" "+result.pack.version;return result;},L"Installing pack\x2026");
    }
    void complete(Completion& completion) {
        if(worker.joinable())worker.join();elapsed_ms=GetTickCount64()-started;busy=false;SendMessageW(progress,PBM_SETMARQUEE,FALSE,0);ShowWindow(progress,SW_HIDE);ShowWindow(footer,SW_SHOW);
        if(completion.imported&&completion.result.success)refresh_packs(completion.pack.root);
        outcome=completion.result.cancelled?0:(completion.result.success?1:-1);
        if(!completion.result.folder.empty()&&bw::directory_exists(completion.result.folder))result_folder=completion.result.folder;
        std::wstring summary=completion.result.cancelled?L"Cancelled. Open details for the run report.":completion.result.success?L"Completed. Your results are ready.":L"The workflow stopped. Open details to see why.";
        if(completion.imported&&completion.result.success)summary=L"Pack installed. Ready when you are.";
        SetWindowTextW(status,summary.c_str());append_log(L"");append_log(completion.result.message.empty()?summary:completion.result.message);
        if(!completion.result.folder.empty())append_log(L"Results folder: "+completion.result.folder);for(const auto& output:completion.result.outputs)append_log(L"Saved: "+output);
        if(!completion.result.success&&!completion.result.cancelled){show_details=true;SetWindowTextW(details_button,L"Hide details  \x2303");layout();}
        update_enabled();update_elapsed();InvalidateRect(status,nullptr,TRUE);if(pending_close)DestroyWindow(window);
    }
    void request_cancel(){if(!busy)return;cancel.store(true);SetWindowTextW(status,L"Stopping the current task\x2026");append_log(L"Cancellation requested.");update_enabled();}
    void update_elapsed(){const auto seconds=(busy?GetTickCount64()-started:elapsed_ms)/1000;wchar_t text[80]{};if(seconds>=3600)std::swprintf(text,80,L"%llu:%02llu:%02llu elapsed",seconds/3600,(seconds/60)%60,seconds%60);else std::swprintf(text,80,L"%02llu:%02llu elapsed",seconds/60,seconds%60);SetWindowTextW(elapsed,text);}
    void command(int id,int notification) {
        if(id==ID_PACK&&!combo_refresh) {
            if(notification==CBN_EDITCHANGE&&!busy){const auto query=control_text(pack_combo);rebuild_pack_combo(query);SendMessageW(pack_combo,CB_SHOWDROPDOWN,TRUE,0);return;}
            if(notification==CBN_SELCHANGE&&!busy){int index=static_cast<int>(SendMessageW(pack_combo,CB_GETCURSEL,0,0));if(index>=0&&static_cast<size_t>(index)<pack_choices.size())select_pack(pack_choices[index]);return;}
        }
        if(id==ID_WORKFLOW&&notification==CBN_SELCHANGE&&!busy){save_fields();selected_workflow=static_cast<int>(SendMessageW(workflow_combo,CB_GETCURSEL,0,0));rebuild_fields();return;}
        if(id>=ID_FIELD){const size_t index=static_cast<size_t>((id-ID_FIELD)/3);if(index<fields.size()&&(id-ID_FIELD)%3==1&&notification==BN_CLICKED&&!busy){auto& f=fields[index];const auto path=choose_path(window,f.input.type,f.input.filter,control_text(f.value),L"Choose "+f.input.label);if(!path.empty())SetWindowTextW(f.value,path.c_str());}return;}
        if(notification!=BN_CLICKED)return;
        switch(id) {
        case ID_RUN:start_job();break;case ID_CANCEL:request_cancel();break;case ID_CHECK:start_check();break;case ID_ADD_PACK:add_pack_folder();break;
        case ID_PREV:select_pack(selected-1);break;case ID_NEXT:select_pack(selected+1);break;
        case ID_DETAILS:show_details=!show_details;SetWindowTextW(details_button,show_details?L"Hide details  \x2303":L"Show details  \x2304");layout();break;
        case ID_OPEN_RESULTS:if(!result_folder.empty()){auto code=reinterpret_cast<INT_PTR>(ShellExecuteW(window,L"open",result_folder.c_str(),nullptr,nullptr,SW_SHOWNORMAL));if(code<=32)show_error(L"Windows could not open the results folder:\n\n"+result_folder);}break;
        case ID_PICK_OUTPUT:if(!busy){const auto path=choose_path(window,L"directory",L"",control_text(output_edit),L"Choose where to save results");if(!path.empty())SetWindowTextW(output_edit,path.c_str());}break;
        }
    }
    std::vector<int> wheel_indices()const {
        std::vector<int> result;if(packs.empty())return result;const int count=static_cast<int>(std::min<size_t>(5,packs.size()));
        for(int i=0;i<count;++i)result.push_back((selected-count/2+i+static_cast<int>(packs.size()))%static_cast<int>(packs.size()));return result;
    }
    void paint_wheel(HWND hwnd) {
        PAINTSTRUCT ps{};HDC dc=BeginPaint(hwnd,&ps);RECT rc{};GetClientRect(hwnd,&rc);
        HDC mem=CreateCompatibleDC(dc);HBITMAP bitmap=CreateCompatibleBitmap(dc,rc.right,rc.bottom);HGDIOBJ old=SelectObject(mem,bitmap);FillRect(mem,&rc,sidebar_brush);
        {
            Gdiplus::Graphics g(mem);g.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);g.SetTextRenderingHint(Gdiplus::TextRenderingHintClearTypeGridFit);g.ScaleTransform(dpi/96.0f*wheel_size/270.0f,dpi/96.0f*wheel_size/270.0f);
            const auto indices=wheel_indices();const float outer=259,inner=137;const float step=indices.empty()?90.0f:90.0f/static_cast<float>(indices.size());
            for(size_t i=0;i<indices.size();++i) {
                const float start=static_cast<float>(i)*step+0.7f,sweep=step-1.4f;
                Gdiplus::GraphicsPath path;path.AddArc(-outer,-outer,outer*2,outer*2,start,sweep);path.AddArc(-inner,-inner,inner*2,inner*2,start+sweep,-sweep);path.CloseFigure();
                const auto pack_color=colorref(packs[indices[i]].color);const bool active=indices[i]==selected;
                Gdiplus::SolidBrush fill(color(active?pack_color:mix(pack_color,SIDEBAR,76)));g.FillPath(&fill,&path);
                if(active){Gdiplus::Pen stroke(color(PAPER),3);g.DrawPath(&stroke,&path);
                    if(GetFocus()==hwnd&&wheel_keyboard_focus) {
                        Gdiplus::GraphicsPath focus_path;const float a=outer-6,b=inner+6;
                        focus_path.AddArc(-a,-a,a*2,a*2,start+1,sweep-2);
                        focus_path.AddArc(-b,-b,b*2,b*2,start+sweep-1,2-sweep);focus_path.CloseFigure();
                        Gdiplus::Pen focus_pen(color(contrast_text(pack_color)),2.2f);focus_pen.SetDashStyle(Gdiplus::DashStyleDot);g.DrawPath(&focus_pen,&focus_path);
                    }
                }
                const double radians=(start+sweep/2)*3.141592653589793/180;const float radius=(inner+outer)/2;
                Gdiplus::FontFamily family(L"Segoe UI");Gdiplus::Font label_font(&family,active?20.0f:16.0f,active?Gdiplus::FontStyleBold:Gdiplus::FontStyleRegular,Gdiplus::UnitPixel);
                const auto segment_fill=active?pack_color:mix(pack_color,SIDEBAR,76);
                Gdiplus::SolidBrush text_brush(color(contrast_text(segment_fill)));Gdiplus::StringFormat format;format.SetAlignment(Gdiplus::StringAlignmentCenter);format.SetLineAlignment(Gdiplus::StringAlignmentCenter);
                const auto number=std::to_wstring(indices[i]+1);Gdiplus::RectF text(static_cast<float>(std::cos(radians))*radius-22,static_cast<float>(std::sin(radians))*radius-19,44,38);g.DrawString(number.c_str(),-1,&label_font,text,&format,&text_brush);
                if(active){Gdiplus::SolidBrush dot(color(PAPER));g.FillEllipse(&dot,static_cast<float>(std::cos(radians))*(outer-15)-3,static_cast<float>(std::sin(radians))*(outer-15)-3,6.0f,6.0f);}
            }
            if(indices.empty()){Gdiplus::SolidBrush empty(color(LINE));g.FillPie(&empty,-outer,-outer,outer*2,outer*2,0,90);Gdiplus::SolidBrush cut(color(SIDEBAR));g.FillEllipse(&cut,-inner,-inner,inner*2,inner*2);}
        }
        auto wpx=[this](int n){return px(MulDiv(n,wheel_size,270));};
        SetBkMode(mem,TRANSPARENT);SetTextColor(mem,MUTED);SelectObject(mem,wheel_size<220?small_font:semibold_font);RECT text{wpx(24),wpx(30),wpx(135),wpx(58)};DrawTextW(mem,L"TOOL PACKS",-1,&text,DT_LEFT|DT_NOPREFIX);
        SetTextColor(mem,INK);SelectObject(mem,wheel_size<220?semibold_font:pack_font);std::wstring count=selected>=0?std::to_wstring(selected+1)+L" / "+std::to_wstring(packs.size()):L"0 / 0";text={wpx(24),wpx(63),wpx(133),wpx(102)};DrawTextW(mem,count.c_str(),-1,&text,DT_LEFT|DT_NOPREFIX);
        BitBlt(dc,0,0,rc.right,rc.bottom,mem,0,0,SRCCOPY);SelectObject(mem,old);DeleteObject(bitmap);DeleteDC(mem);EndPaint(hwnd,&ps);
    }
    double wheel_angle(LPARAM lp)const {return std::atan2(static_cast<double>(GET_Y_LPARAM(lp)),static_cast<double>(GET_X_LPARAM(lp)))*180.0/3.141592653589793;}
    LRESULT wheel_message(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp) {
        switch(msg) {
        case WM_PAINT:paint_wheel(hwnd);return 0;case WM_ERASEBKGND:return 1;
        case WM_GETDLGCODE:return DLGC_WANTARROWS;
        case WM_SETFOCUS:wheel_keyboard_focus=!wheel_pointer_focus;InvalidateRect(hwnd,nullptr,FALSE);return 0;
        case WM_KILLFOCUS:wheel_keyboard_focus=false;InvalidateRect(hwnd,nullptr,FALSE);return 0;
        case WM_KEYDOWN:wheel_keyboard_focus=true;InvalidateRect(hwnd,nullptr,FALSE);if(!busy){if(wp==VK_LEFT||wp==VK_UP)select_pack(selected-1);else if(wp==VK_RIGHT||wp==VK_DOWN)select_pack(selected+1);else if(wp==VK_HOME)select_pack(0);else if(wp==VK_END)select_pack(static_cast<int>(packs.size())-1);}return 0;
        case WM_MOUSEWHEEL:wheel_keyboard_focus=false;InvalidateRect(hwnd,nullptr,FALSE);if(!busy&&GET_WHEEL_DELTA_WPARAM(wp)!=0)select_pack(selected+(GET_WHEEL_DELTA_WPARAM(wp)>0?-1:1));return 0;
        case WM_LBUTTONDOWN:if(!busy&&!packs.empty()){wheel_pointer_focus=true;SetFocus(hwnd);wheel_pointer_focus=false;wheel_keyboard_focus=false;InvalidateRect(hwnd,nullptr,FALSE);const double x=GET_X_LPARAM(lp)/static_cast<double>(px(wheel_size))*270,y=GET_Y_LPARAM(lp)/static_cast<double>(px(wheel_size))*270,r=std::hypot(x,y);if(r>=137&&r<=260){dragging=true;drag_moved=false;drag_angle=wheel_angle(lp);drag_selection=selected;SetCapture(hwnd);}}return 0;
        case WM_MOUSEMOVE:if(dragging){double delta=wheel_angle(lp)-drag_angle;int move=static_cast<int>(delta/15.0);if(move){drag_moved=true;select_pack(drag_selection-move);}}return 0;
        case WM_LBUTTONUP:if(dragging){dragging=false;ReleaseCapture();if(!drag_moved){auto indices=wheel_indices();const int slot=std::clamp(static_cast<int>(wheel_angle(lp)/90.0*indices.size()),0,static_cast<int>(indices.size())-1);if(!indices.empty())select_pack(indices[slot]);}}return 0;
        case WM_CAPTURECHANGED:dragging=false;return 0;
        }
        return DefWindowProcW(hwnd,msg,wp,lp);
    }
    void paint_window() {
        PAINTSTRUCT ps{};HDC dc=BeginPaint(window,&ps);RECT r{};GetClientRect(window,&r);FillRect(dc,&r,canvas_brush);
        {
            // Destroy Graphics/Matrix before EndPaint releases their device context.
            Gdiplus::Matrix transform(dpi/96.0f,0,0,dpi/96.0f,static_cast<float>(-px(workspace_x)),static_cast<float>(-px(workspace_y)));
            Gdiplus::Graphics g(dc);g.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);g.SetTransform(&transform);
            Gdiplus::SolidBrush side(color(SIDEBAR));g.FillRectangle(&side,0,0,sidebar_width,height);
            rounded(g,14,static_cast<float>(sidebar_card_top),static_cast<float>(sidebar_width-28),compact?111.0f:187.0f,16,mix(accent(),PAPER,7));
            rounded(g,static_cast<float>(main_x),static_cast<float>(form_card_top),static_cast<float>(main_width),static_cast<float>(std::max(1,form_bottom-form_card_top+10)),16,PAPER,LINE);
            if(show_details&&!log_replaces_form)rounded(g,static_cast<float>(main_x),static_cast<float>(output_top-detail_height),static_cast<float>(main_width),static_cast<float>(detail_height-9),12,PAPER,LINE);
            rounded(g,static_cast<float>(main_x),static_cast<float>(output_top+27),static_cast<float>(main_width-107),37,8,PAPER,GetFocus()==output_edit?accent():LINE);
        }
        EndPaint(window,&ps);
    }
    void draw_button(const DRAWITEMSTRUCT& item) {
        RECT r=item.rcItem;const bool disabled=(item.itemState&ODS_DISABLED)!=0,pressed=(item.itemState&ODS_SELECTED)!=0,focus=(item.itemState&ODS_FOCUS)!=0;
        const bool primary=item.CtlID==ID_RUN;const bool nav=item.CtlID==ID_PREV||item.CtlID==ID_NEXT;const bool on_sidebar=item.hwndItem==add_pack||item.hwndItem==check_button||nav;
        FillRect(item.hDC,&r,on_sidebar?sidebar_brush:GetParent(item.hwndItem)==form?paper_brush:canvas_brush);
        Gdiplus::Graphics g(item.hDC);g.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
        COLORREF fill=primary?mix(accent(),INK,80):PAPER,stroke=primary?mix(accent(),INK,80):LINE,text=primary?contrast_text(fill):INK;
        if(disabled){fill=primary?mix(accent(),CANVAS,35):mix(PAPER,CANVAS,50);text=primary?PAPER:RGB(148,157,172);stroke=LINE;}
        else if(pressed)fill=mix(fill,primary?INK:accent(),primary?78:90);
        rounded(g,0.5f,0.5f,static_cast<float>(r.right-1),static_cast<float>(r.bottom-1),static_cast<float>(px(9)),fill,focus?accent():stroke);
        SelectObject(item.hDC,primary?semibold_font:font);SetTextColor(item.hDC,text);SetBkMode(item.hDC,TRANSPARENT);const auto caption=control_text(item.hwndItem);DrawTextW(item.hDC,caption.c_str(),-1,&r,DT_CENTER|DT_VCENTER|DT_SINGLELINE);
        if(focus){InflateRect(&r,-px(5),-px(5));DrawFocusRect(item.hDC,&r);}
    }
    LRESULT control_color(UINT msg,WPARAM wp,LPARAM lp) {
        const HWND h=reinterpret_cast<HWND>(lp);HDC dc=reinterpret_cast<HDC>(wp);COLORREF background=CANVAS,foreground=INK;HBRUSH brush=canvas_brush;
        const bool sidebar=h==pack_name||h==pack_version||h==pack_description||h==wheel_hint||h==pack_label||h==local_label;
        if(sidebar){background=SIDEBAR;brush=sidebar_brush;}
        if(h==pack_name||h==pack_version||h==pack_description){background=mix(accent(),PAPER,7);static HBRUSH pack_brush=nullptr;static COLORREF last=0;if(!pack_brush||last!=background){if(pack_brush)DeleteObject(pack_brush);pack_brush=CreateSolidBrush(background);last=background;}brush=pack_brush;}
        if(GetParent(h)==form||h==log_edit||h==output_edit||msg==WM_CTLCOLOREDIT){background=PAPER;brush=paper_brush;}
        if(h==inputs_label){background=PAPER;brush=paper_brush;}
        if(h==subtitle||h==description||h==steps_label||h==outputs_label||h==output_note||h==pack_description||h==pack_version||h==wheel_hint||h==elapsed||h==footer)foreground=MUTED;
        if(h==local_label)foreground=RGB(50,115,96);
        for(const auto& f:fields)if(h==f.help)foreground=MUTED;
        if(h==status&&outcome)foreground=outcome>0?RGB(39,122,94):RGB(177,62,72);
        if(!IsWindowEnabled(h))foreground=RGB(143,153,168);
        SetTextColor(dc,foreground);SetBkColor(dc,background);return reinterpret_cast<LRESULT>(brush);
    }
    LRESULT handle(UINT msg,WPARAM wp,LPARAM lp) {
        switch(msg) {
        case WM_CREATE:create_controls();return 0;
        case MSG_INITIALIZE:refresh_packs();append_log(L"Ready. Runs create their own output folders and logs.");if(auto_check&&!packs.empty())start_check();return 0;
        case WM_COMMAND:command(LOWORD(wp),HIWORD(wp));return 0;
        case WM_DRAWITEM:draw_button(*reinterpret_cast<DRAWITEMSTRUCT*>(lp));return TRUE;
        case DM_GETDEFID:return MAKELRESULT(ID_RUN,DC_HASDEFID);
        case WM_SIZE:layout();return 0;
        case WM_PAINT:paint_window();return 0;
        case WM_ERASEBKGND:{RECT r{};GetClientRect(window,&r);FillRect(reinterpret_cast<HDC>(wp),&r,canvas_brush);return 1;}
        case WM_GETMINMAXINFO:{auto* info=reinterpret_cast<MINMAXINFO*>(lp);MONITORINFO monitor{};monitor.cbSize=sizeof(monitor);GetMonitorInfoW(MonitorFromWindow(window,MONITOR_DEFAULTTONEAREST),&monitor);info->ptMinTrackSize.x=std::min<LONG>(px(900),monitor.rcWork.right-monitor.rcWork.left);info->ptMinTrackSize.y=std::min<LONG>(px(690),monitor.rcWork.bottom-monitor.rcWork.top);return 0;}
        case WM_DPICHANGED:{dpi=HIWORD(wp);set_fonts();auto* r=reinterpret_cast<RECT*>(lp);SetWindowPos(window,nullptr,r->left,r->top,r->right-r->left,r->bottom-r->top,SWP_NOZORDER|SWP_NOACTIVATE);layout();return 0;}
        case WM_VSCROLL:if(lp==0){workspace_scroll_command(false,LOWORD(wp));return 0;}break;
        case WM_HSCROLL:if(lp==0){workspace_scroll_command(true,LOWORD(wp));return 0;}break;
        case WM_MOUSEHWHEEL:scroll_workspace(true,GET_WHEEL_DELTA_WPARAM(wp)*54/WHEEL_DELTA);return 0;
        case WM_MOUSEWHEEL:{
            const int amount=-GET_WHEEL_DELTA_WPARAM(wp)*54/WHEEL_DELTA;
            if((GET_KEYSTATE_WPARAM(wp)&MK_SHIFT)&&width>viewport_width)scroll_workspace(true,amount);
            else if(height>viewport_height)scroll_workspace(false,amount);
            else {POINT p{GET_X_LPARAM(lp),GET_Y_LPARAM(lp)};ScreenToClient(window,&p);if(p.x<px(sidebar_width-workspace_x))SendMessageW(wheel,msg,wp,lp);else scroll_by(amount);}
            return 0;
        }
        case WM_TIMER:if(wp==TIMER_ELAPSED&&busy)update_elapsed();return 0;
        case MSG_LOG:{std::unique_ptr<std::wstring> text(reinterpret_cast<std::wstring*>(lp));append_log(*text);return 0;}
        case MSG_PHASE:{std::unique_ptr<std::wstring> text(reinterpret_cast<std::wstring*>(lp));if(!cancel.load())SetWindowTextW(status,text->c_str());return 0;}
        case MSG_COMPLETE:{std::unique_ptr<Completion> result(reinterpret_cast<Completion*>(lp));complete(*result);return 0;}
        case WM_CTLCOLORSTATIC:case WM_CTLCOLOREDIT:case WM_CTLCOLORBTN:return control_color(msg,wp,lp);
        case WM_CLOSE:if(busy){if(pending_close)return 0;if(MessageBoxW(window,L"A task is running. Stop it and close Native Workbench?",L"Close Native Workbench",MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2)!=IDYES)return 0;if(busy){pending_close=true;request_cancel();return 0;}}DestroyWindow(window);return 0;
        case WM_DESTROY:cancel.store(true);KillTimer(window,TIMER_ELAPSED);PostQuitMessage(0);return 0;
        default:return DefWindowProcW(window,msg,wp,lp);
        }
        return DefWindowProcW(window,msg,wp,lp);
    }
};
}

int WINAPI wWinMain(HINSTANCE instance,HINSTANCE,PWSTR,int show) {
    using AwarenessFn=BOOL(WINAPI*)(DPI_AWARENESS_CONTEXT);auto awareness=reinterpret_cast<AwarenessFn>(GetProcAddress(GetModuleHandleW(L"user32.dll"),"SetProcessDpiAwarenessContext"));
    if(awareness)awareness(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);else SetProcessDPIAware();
    const HRESULT com=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED|COINIT_DISABLE_OLE1DDE);
    if(FAILED(com)){MessageBoxW(nullptr,L"Windows could not initialize the file pickers.",L"Native Workbench",MB_OK|MB_ICONERROR);return 1;}
    Gdiplus::GdiplusStartupInput input;ULONG_PTR graphics_token=0;
    if(Gdiplus::GdiplusStartup(&graphics_token,&input,nullptr)!=Gdiplus::Ok){CoUninitialize();MessageBoxW(nullptr,L"Windows could not initialize the interface.",L"Native Workbench",MB_OK|MB_ICONERROR);return 1;}
    INITCOMMONCONTROLSEX common{sizeof(common),ICC_PROGRESS_CLASS|ICC_STANDARD_CLASSES};InitCommonControlsEx(&common);int result=1;
    {
        Application app;app.instance=instance;int count=0;LPWSTR* args=CommandLineToArgvW(GetCommandLineW(),&count);
        if(args){for(int i=1;i<count;++i)if(std::wcscmp(args[i],L"--check")==0)app.auto_check=true;LocalFree(args);}
        WNDCLASSEXW klass{};klass.cbSize=sizeof(klass);klass.style=CS_HREDRAW|CS_VREDRAW;klass.lpfnWndProc=Application::procedure;klass.hInstance=instance;
        klass.hIcon=LoadIconW(nullptr,IDI_APPLICATION);klass.hIconSm=klass.hIcon;klass.hCursor=LoadCursorW(nullptr,IDC_ARROW);klass.lpszClassName=L"NativeWorkbenchDesktop040";
        WNDCLASSEXW child=klass;child.lpfnWndProc=Application::child_procedure;child.lpszClassName=L"NativeWorkbenchSurface040";child.hIcon=nullptr;child.hIconSm=nullptr;
        if(RegisterClassExW(&klass)&&RegisterClassExW(&child)) {
            HDC dc=GetDC(nullptr);int dpi=dc?GetDeviceCaps(dc,LOGPIXELSX):96;if(dc)ReleaseDC(nullptr,dc);
            RECT area{};SystemParametersInfoW(SPI_GETWORKAREA,0,&area,0);
            int start_width=std::min<int>(MulDiv(1220,dpi,96),area.right-area.left),start_height=std::min<int>(MulDiv(860,dpi,96),area.bottom-area.top);
            HWND window=CreateWindowExW(WS_EX_CONTROLPARENT,klass.lpszClassName,L"Native Workbench",WS_OVERLAPPEDWINDOW|WS_CLIPCHILDREN,CW_USEDEFAULT,CW_USEDEFAULT,start_width,start_height,nullptr,nullptr,instance,&app);
            if(window){ShowWindow(window,show);UpdateWindow(window);MSG message{};BOOL received;while((received=GetMessageW(&message,nullptr,0,0))>0){if(!IsDialogMessageW(window,&message)){TranslateMessage(&message);DispatchMessageW(&message);}}result=received==-1?1:static_cast<int>(message.wParam);}
        }else MessageBoxW(nullptr,L"Windows could not create the application window.",L"Native Workbench",MB_OK|MB_ICONERROR);
    }
    Gdiplus::GdiplusShutdown(graphics_token);CoUninitialize();return result;
}
