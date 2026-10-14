"""UI test fixture. Real API/graph validation; simulated native dialog/execution.
Run: python tests/ui_fixture_server.py --app-root PATH_TO_EXTRACTED_WORKBENCH
Then run test_ui_browser.cjs with the printed localhost URL and test output path.
This never runs the Windows tools and is not native runtime validation.
"""
import argparse
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import Workbench, LocalServer
parser = argparse.ArgumentParser()
parser.add_argument('--app-root', type=Path, required=True)
args = parser.parse_args()
app = Workbench(args.app_root)
app.web = Path(__file__).resolve().parent.parent / 'web'
with tempfile.TemporaryDirectory(prefix='workbench-ui-qa-') as temporary:
    app.data = Path(temporary)
    app.saved_path = app.data / 'saved.json'
    app.history_path = app.data / 'runs.json'
    app.history = []
    app.browse = lambda req: {'paths': [str(app.root / 'examples/variant-truth/reference.fa')] if req['kind'] == 'file' else [temporary]}
    def execute(plan, event, cancel):
        for node in plan['nodes']:
            event({'type': 'step', 'nodeId': node['id'], 'status': 'running'})
            time.sleep(.08)
            event({'type': 'step', 'nodeId': node['id'], 'status': 'success'})
        return {'status': 'success', 'folder': plan['folder'], 'nodes': [
            {'id': n['id'], 'name': n.get('label', n.get('name', n['id'])), 'tool': n['tool'], 'status': 'success'} for n in plan['nodes']],
            'methods': plan['methods'], 'outputs': {}, 'graph': plan['graph']}
    app.engine.execute = execute
    server = LocalServer(app)
    print(server.origin + '/#' + app.token, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
