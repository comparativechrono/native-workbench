#pragma once

#include "desktop_ipc.h"

namespace desktop {

// A native list may ask for its selection during creation, before an async
// reply, after a search removes rows, or while a previous row is deselected.
// None of these states is a selected record. Keep this shared by the catalogue
// and results views so their enable/selection callbacks never dereference a
// missing JSON array or an old row index.
inline const Json& selected_record(const Json& state, const char* key, int row) {
    static const Json empty = Json::object();
    const auto& records = state.get(key);
    if (row < 0 || !records.is_array()) return empty;
    const auto& values = records.array_items();
    const auto index = static_cast<std::size_t>(row);
    if (index >= values.size() || !values[index].is_object()) return empty;
    return values[index];
}

} // namespace desktop
