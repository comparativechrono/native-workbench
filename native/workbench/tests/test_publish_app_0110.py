#!/usr/bin/env python3
"""Network-free tests of immutable promotion refusal and read-only guards."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).resolve().parents[1] / 'scripts/publish_app_0110.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

def valid_lock():
    return json.loads("{\n  \"schema\": 1,\n  \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n  \"prNumber\": 6,\n  \"coreFiles\": 72,\n  \"authorization\": {\n    \"message\": \"Please release 0.11.0 properly\",\n    \"authorized\": true,\n    \"date\": \"2026-10-07\"\n  },\n  \"archives\": {\n    \"native-workbench-0.11.0-starter-windows.zip\": {\n      \"bytes\": 17044022,\n      \"sha256\": \"e816e2f7cd5efe98af752fbf072fab00344ebaa2b6963795c2fbf4a86b5fa81c\"\n    },\n    \"native-workbench-0.11.0-source.zip\": {\n      \"bytes\": 46875983,\n      \"sha256\": \"a45ad640f0767bb56458b59ce50d263537e54ebb401a0e809f31a5453adb2f2b\"\n    },\n    \"native-workbench-0.11.0-update-from-0.10.1.zip\": {\n      \"bytes\": 12857609,\n      \"sha256\": \"720d79aac5ddfd15dd3d06096950f3e56eff911981643eb6440ecb0f9911ecfe\"\n    }\n  },\n  \"runs\": {\n    \"candidate\": {\n      \"id\": 37678010251,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"path\": \".github/workflows/native-tool-library-candidate.yml\",\n      \"conclusion\": \"failure\",\n      \"jobs\": [\n        {\n          \"id\": 112986418456,\n          \"name\": \"build\",\n          \"conclusion\": \"success\",\n          \"nonSuccessSteps\": []\n        },\n        {\n          \"id\": 112986888068,\n          \"name\": \"native (ordinary)\",\n          \"conclusion\": \"failure\",\n          \"nonSuccessSteps\": [\n            {\n              \"name\": \"Native expandable categories, search, selection, scrolling and installed-pack refresh\",\n              \"conclusion\": \"failure\"\n            }\n          ]\n        },\n        {\n          \"id\": 112986888194,\n          \"name\": \"native (path with spaces)\",\n          \"conclusion\": \"failure\",\n          \"nonSuccessSteps\": [\n            {\n              \"name\": \"Native expandable categories, search, selection, scrolling and installed-pack refresh\",\n              \"conclusion\": \"failure\"\n            }\n          ]\n        }\n      ]\n    },\n    \"categories\": {\n      \"id\": 37678715894,\n      \"sourceCommit\": \"3c2d5079355e6a056dcdbe39f25b7b7bead7d670\",\n      \"path\": \".github/workflows/native-tool-library-verify.yml\",\n      \"conclusion\": \"success\",\n      \"jobs\": [\n        {\n          \"id\": 112988861775,\n          \"name\": \"native (path with spaces)\",\n          \"conclusion\": \"success\",\n          \"nonSuccessSteps\": []\n        },\n        {\n          \"id\": 112988861990,\n          \"name\": \"native (ordinary)\",\n          \"conclusion\": \"success\",\n          \"nonSuccessSteps\": []\n        }\n      ]\n    },\n    \"updater\": {\n      \"id\": 37683536378,\n      \"sourceCommit\": \"f13e2c6dde1c1792405617af943dc706dfd42176\",\n      \"path\": \".github/workflows/native-update-0.11.0.yml\",\n      \"conclusion\": \"success\",\n      \"jobs\": [\n        {\n          \"id\": 113005384378,\n          \"name\": \"build\",\n          \"conclusion\": \"success\",\n          \"nonSuccessSteps\": []\n        },\n        {\n          \"id\": 113005564920,\n          \"name\": \"native (ordinary)\",\n          \"conclusion\": \"success\",\n          \"nonSuccessSteps\": []\n        },\n        {\n          \"id\": 113005564977,\n          \"name\": \"native (path with spaces)\",\n          \"conclusion\": \"success\",\n          \"nonSuccessSteps\": []\n        }\n      ]\n    },\n    \"regressions\": {\n      \"id\": 37685190036,\n      \"sourceCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"path\": \".github/workflows/native-library-release-check.yml\",\n      \"conclusion\": \"success\",\n      \"jobs\": [\n        {\n          \"id\": 113011077214,\n          \"name\": \"native (ordinary)\",\n          \"conclusion\": \"success\",\n          \"nonSuccessSteps\": []\n        },\n        {\n          \"id\": 113011077667,\n          \"name\": \"native (path with spaces)\",\n          \"conclusion\": \"success\",\n          \"nonSuccessSteps\": []\n        }\n      ]\n    }\n  },\n  \"artifacts\": {\n    \"candidate\": {\n      \"id\": 11507920876,\n      \"name\": \"tool-library-candidate-acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"bytes\": 63424882,\n      \"sha256\": \"ab2ceafc3515cbf5dd0af9f9d1815358bb3c0fab99cdec57b45bade2490d7218\",\n      \"run\": \"candidate\",\n      \"file\": \"candidate.zip\"\n    },\n    \"workspace-ordinary\": {\n      \"id\": 11508505527,\n      \"name\": \"tool-library-windows-ordinary-1\",\n      \"bytes\": 862356,\n      \"sha256\": \"d7d814fa0ec988e76dab8fb993e6b9227f1c8cda8c0d67031921e993e7e31c03\",\n      \"run\": \"candidate\",\n      \"file\": \"workspace-ordinary.zip\"\n    },\n    \"workspace-spaces\": {\n      \"id\": 11508380589,\n      \"name\": \"tool-library-windows-path with spaces-1\",\n      \"bytes\": 860361,\n      \"sha256\": \"4ccf9793503276d622868ea8dc1479a53e3b7d36d732748691b2b85681689b02\",\n      \"run\": \"candidate\",\n      \"file\": \"workspace-spaces.zip\"\n    },\n    \"library-ordinary\": {\n      \"id\": 11507976693,\n      \"name\": \"tool-library-verified-ordinary-1\",\n      \"bytes\": 1313443,\n      \"sha256\": \"48996310a819b1affa0c8d03804cae5eb6fc9f8ad57392825dfdcee9add35f12\",\n      \"run\": \"categories\",\n      \"file\": \"library-ordinary.zip\"\n    },\n    \"library-spaces\": {\n      \"id\": 11509095498,\n      \"name\": \"tool-library-verified-path with spaces-1\",\n      \"bytes\": 1312501,\n      \"sha256\": \"e77a7e08a7f9ef5b383466e6cbbb424030861ca56e7eee72ca3d5972ed2bc5dd\",\n      \"run\": \"categories\",\n      \"file\": \"library-spaces.zip\"\n    },\n    \"updater\": {\n      \"id\": 11510267028,\n      \"name\": \"update-0.11.0-from-0.10.1-f13e2c6dde1c1792405617af943dc706dfd42176\",\n      \"bytes\": 12860880,\n      \"sha256\": \"e6b4f9058fe65c9b56d89362b2687fa1e6ff8cd97a5bd446cbe9e9eb76825395\",\n      \"run\": \"updater\",\n      \"file\": \"updater.zip\"\n    },\n    \"update-ordinary\": {\n      \"id\": 11509398431,\n      \"name\": \"update-0.11.0-ordinary-1\",\n      \"bytes\": 287931,\n      \"sha256\": \"9b822b46eeba49c83a124ede986a51a006ca641192fc5cfea1fc32c5f85c6a07\",\n      \"run\": \"updater\",\n      \"file\": \"update-ordinary.zip\"\n    },\n    \"update-spaces\": {\n      \"id\": 11510092713,\n      \"name\": \"update-0.11.0-path with spaces-1\",\n      \"bytes\": 288266,\n      \"sha256\": \"dbbdb09cd753c63b3aa22ab5cec5c84410cc2c8a98942dc4cee6736b9b75981c\",\n      \"run\": \"updater\",\n      \"file\": \"update-spaces.zip\"\n    },\n    \"regressions-ordinary\": {\n      \"id\": 11510906175,\n      \"name\": \"tool-library-release-checks-ordinary-1\",\n      \"bytes\": 2412375,\n      \"sha256\": \"7fc115455e28848a272769214272f7dc8a03a153647030f1f5e6434ae8cf17de\",\n      \"run\": \"regressions\",\n      \"file\": \"regressions-ordinary.zip\"\n    },\n    \"regressions-spaces\": {\n      \"id\": 11510444954,\n      \"name\": \"tool-library-release-checks-path with spaces-1\",\n      \"bytes\": 2413585,\n      \"sha256\": \"e75d7fcc05f5842ac1c4c274027a3f6a442eadb8886b2dd1cbb3c272ee2e5c00\",\n      \"run\": \"regressions\",\n      \"file\": \"regressions-spaces.zip\"\n    }\n  },\n  \"reports\": {\n    \"ordinary-workspace\": {\n      \"kind\": \"workspace\",\n      \"artifact\": \"workspace-ordinary\",\n      \"path\": \"workspace-evidence/native-ui.json\",\n      \"sha256\": \"f9ae55647b66a71f0935b8582469e84dd9aa83368d6c7e027b90a896ad3e6744\",\n      \"passed\": 32,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"gate\": \"scripts/check_workspace_ui_windows.py\",\n      \"gateCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"skips\": []\n    },\n    \"ordinary-library\": {\n      \"kind\": \"library\",\n      \"artifact\": \"regressions-ordinary\",\n      \"path\": \"library-evidence/native-tool-library.json\",\n      \"sha256\": \"e13aa7aba961da484de57183a6214b41ad9f66c87aae4e3e73482d33acfb095b\",\n      \"passed\": 7,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"gate\": \"scripts/check_tool_library_windows.py\",\n      \"gateCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"skips\": []\n    },\n    \"ordinary-results\": {\n      \"kind\": \"results\",\n      \"artifact\": \"regressions-ordinary\",\n      \"path\": \"results-evidence/native-results.json\",\n      \"sha256\": \"9edf58e638163cfa92589047e7b874df96a81fc05e23a6c744edd29e14e9c8c8\",\n      \"passed\": 9,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"gate\": \"scripts/check_results_windows.py\",\n      \"gateCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"skips\": []\n    },\n    \"ordinary-references\": {\n      \"kind\": \"references\",\n      \"artifact\": \"regressions-ordinary\",\n      \"path\": \"references-evidence/native-references.json\",\n      \"sha256\": \"12de4da1ad259d05d92052b87b770c3e1c2c6c6c7710d864cf7ddf2198da1ac4\",\n      \"passed\": 8,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"gate\": \"scripts/check_references_windows.py\",\n      \"gateCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"skips\": [\n        \"Optional native core updater gate was not requested.\"\n      ]\n    },\n    \"ordinary-scroll\": {\n      \"kind\": \"scroll\",\n      \"artifact\": \"regressions-ordinary\",\n      \"path\": \"scroll-evidence/native-scroll.json\",\n      \"sha256\": \"e06c8b38b59da8ea9ef3ea62a1d3fd21c3dac65e2c4aa823e4d8f05029b238a6\",\n      \"passed\": 3,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"gate\": \"scripts/check_scroll_frames_windows.py\",\n      \"gateCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"skips\": []\n    },\n    \"ordinary-update\": {\n      \"kind\": \"update\",\n      \"artifact\": \"update-ordinary\",\n      \"path\": \"update-native.json\",\n      \"sha256\": \"0ea5a1af1d05017893dc8471cac39cc0f5d1be6c9ffcb7c33ad86fa626b0f481\",\n      \"passed\": 13,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"f13e2c6dde1c1792405617af943dc706dfd42176\",\n      \"gate\": \"scripts/check_update_0110_windows.py\",\n      \"gateCommit\": \"f13e2c6dde1c1792405617af943dc706dfd42176\",\n      \"skips\": []\n    },\n    \"spaces-workspace\": {\n      \"kind\": \"workspace\",\n      \"artifact\": \"workspace-spaces\",\n      \"path\": \"workspace-evidence/native-ui.json\",\n      \"sha256\": \"d3cf36550b1bed77bdf42704a439f8c183f9f8ce2c7d00852746a46a23fb4b69\",\n      \"passed\": 32,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"gate\": \"scripts/check_workspace_ui_windows.py\",\n      \"gateCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"skips\": []\n    },\n    \"spaces-library\": {\n      \"kind\": \"library\",\n      \"artifact\": \"regressions-spaces\",\n      \"path\": \"library-evidence/native-tool-library.json\",\n      \"sha256\": \"7d38bce001bb9e635492fdc46eab7b1bbc39709fa552f03c12f7ebb0736f4e93\",\n      \"passed\": 7,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"gate\": \"scripts/check_tool_library_windows.py\",\n      \"gateCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"skips\": []\n    },\n    \"spaces-results\": {\n      \"kind\": \"results\",\n      \"artifact\": \"regressions-spaces\",\n      \"path\": \"results-evidence/native-results.json\",\n      \"sha256\": \"df20e87a5407fc6145dca9ea357b22e349104515ab794ce6466a7bd61f6fbd7a\",\n      \"passed\": 9,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"gate\": \"scripts/check_results_windows.py\",\n      \"gateCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"skips\": []\n    },\n    \"spaces-references\": {\n      \"kind\": \"references\",\n      \"artifact\": \"regressions-spaces\",\n      \"path\": \"references-evidence/native-references.json\",\n      \"sha256\": \"0f5feae7dc846a9acffab0aba985108f59c53da442c301740c8b850e715b527f\",\n      \"passed\": 8,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"gate\": \"scripts/check_references_windows.py\",\n      \"gateCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"skips\": [\n        \"Optional native core updater gate was not requested.\"\n      ]\n    },\n    \"spaces-scroll\": {\n      \"kind\": \"scroll\",\n      \"artifact\": \"regressions-spaces\",\n      \"path\": \"scroll-evidence/native-scroll.json\",\n      \"sha256\": \"ff105481219c68a6c9fa5d32e132a8a1962e123046187faea8da452978df9939\",\n      \"passed\": 3,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"gate\": \"scripts/check_scroll_frames_windows.py\",\n      \"gateCommit\": \"0c880d1060f22edb7e9c663743a1966a2f8f2eea\",\n      \"skips\": []\n    },\n    \"spaces-update\": {\n      \"kind\": \"update\",\n      \"artifact\": \"update-spaces\",\n      \"path\": \"update-native.json\",\n      \"sha256\": \"b07e2139f454257c869512f6a8f106a7f6f8b7746576398a6c2de16c002ced13\",\n      \"passed\": 13,\n      \"sourceCommit\": \"acfa060c9a400d82509278b657ee37853c7922b0\",\n      \"validatorCommit\": \"f13e2c6dde1c1792405617af943dc706dfd42176\",\n      \"gate\": \"scripts/check_update_0110_windows.py\",\n      \"gateCommit\": \"f13e2c6dde1c1792405617af943dc706dfd42176\",\n      \"skips\": []\n    }\n  }\n}\n")

class PromotionGuards(unittest.TestCase):
    def test_read_only_client_rejects_mutations_before_network(self):
        client = p.ReadOnlyGitHub('test-not-a-secret')
        with patch.object(p.GitHub, 'api') as network:
            for method in ('POST', 'PATCH', 'DELETE'):
                with self.assertRaises(ValueError):
                    client.api('/releases', method, {'draft': False})
            with self.assertRaises(ValueError):
                client.api('/releases', data={})
            network.assert_not_called()

    def test_redirect_strips_api_authorization(self):
        # Redirects are deliberately surfaced to download(), whose next request
        # must carry only the octet-stream header, never the API bearer token.
        self.assertIsNone(p.NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://example.com'))
        source = Path(p.__file__).read_text()
        self.assertIn('headers = {"Accept": "application/octet-stream"}', source)

    def test_zip_refuses_traversal_and_duplicates(self):
        for names in (['../escape'], ['/absolute'], ['C:/drive'], ['back\\slash'], ['same', 'same']):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as z:
                for name in names:
                    z.writestr(name, b'fixture')
            with self.assertRaises(ValueError):
                p.checked_zip(raw.getvalue())

    def test_checksum_inventory_and_content_are_exact(self):
        raw = b'fixture'
        good = (p.sha(raw) + '  asset.zip\n').encode()
        p.checksums(good, {'asset.zip'}, lambda _: raw)
        for value in (good + good, good.replace(b'asset.zip', b'other.zip'), good.replace(p.sha(raw).encode(), b'0' * 64)):
            with self.assertRaises(ValueError):
                p.checksums(value, {'asset.zip'}, lambda _: raw)

    def test_lock_refuses_missing_or_changed_candidate_identity(self):
        for mutate in (
            lambda v: v.update(sourceCommit='0' * 40),
            lambda v: v['archives'][p.STARTER].update(sha256='0' * 64),
            lambda v: v['artifacts'].pop('candidate'),
            lambda v: v['reports'].pop('ordinary-workspace'),
            lambda v: v['artifacts']['workspace-ordinary'].update(id=v['artifacts']['candidate']['id']),
        ):
            value = valid_lock()
            mutate(value)
            with patch.object(p, 'LOCK_PATH', Mock(read_bytes=lambda: json.dumps(value).encode())):
                with self.assertRaises(ValueError):
                    p.acceptance_lock()
        value = valid_lock()
        with patch.object(p, 'LOCK_PATH', Mock(read_bytes=lambda: json.dumps(value).encode())):
            self.assertEqual(p.acceptance_lock(), value)

    def test_application_mutation_is_rejected(self):
        with patch.object(p.subprocess, 'run'), patch.object(p.subprocess, 'check_output', return_value='desktop/desktop_workspace.cpp\n'):
            with self.assertRaises(ValueError):
                p.verify_source_identity('d' * 40)

    def test_publication_requires_exact_main_and_merged_feature_pr(self):
        client = Mock()
        client.api.side_effect = [{'object': {'sha': 'd' * 40}}, {
            'merged': False, 'merge_commit_sha': 'd' * 40,
            'base': {'ref': 'main'}, 'head': {'ref': 'feature/expandable-tool-library'}}]
        with self.assertRaises(ValueError):
            p.verify_merged(client, 'd' * 40)
        self.assertTrue(all(call.args[1:] == () for call in client.api.call_args_list))

    def test_wrong_publication_branch_stops_before_network(self):
        args = types.SimpleNamespace(publish_sha='d' * 40)
        with patch.dict(p.os.environ, {'GITHUB_REPOSITORY': p.REPOSITORY,
            'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': args.publish_sha}, clear=True), patch.object(p, 'GitHub') as network:
            with self.assertRaises(ValueError):
                p.publish(args)
            network.assert_not_called()

    def test_existing_release_is_never_replaced(self):
        args = types.SimpleNamespace(publish_sha='d' * 40)
        client = Mock()
        client.api.return_value = {'object': {'sha': 'a' * 40}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs/releases').mkdir(parents=True)
            (root / 'docs/releases/0.11.0.md').write_text('0.11.0 ' + 'release ' * 40)
            with patch.dict(p.os.environ, {'GITHUB_REPOSITORY': p.REPOSITORY,
                'GITHUB_REF': 'refs/heads/' + p.BRANCH, 'GITHUB_SHA': args.publish_sha}, clear=True), \
                patch.object(p, 'ROOT', root), patch.object(p, 'acceptance_lock', return_value=valid_lock()), \
                patch.object(p, 'verify_source_identity'), patch.object(p, 'GitHub', return_value=client), \
                patch.object(p, 'download_artifacts') as downloads:
                with self.assertRaises(ValueError):
                    p.publish(args)
                downloads.assert_not_called()
                self.assertTrue(all(call.args[1:] == () for call in client.api.call_args_list))

    def test_native_report_rejects_skipped_required_scope(self):
        report = {'success': True, 'nativeWindowsExecuted': True, 'passed': 7,
                  'sourceCommit': p.SOURCE, 'skips': ['Unavailable GUI']}
        raw = json.dumps(report).encode()
        spec = {'sha256': p.sha(raw), 'passed': 7, 'skips': [], 'gate': 'scripts/gate.py', 'gateCommit': p.SOURCE}
        with self.assertRaises(ValueError):
            p.check_report(raw, spec, {}, valid_lock())

    def test_release_inventory_has_eleven_distinct_assets(self):
        self.assertEqual(len(p.ASSET_NAMES), 11)
        self.assertIn('UPDATE-SHA256SUMS.txt', p.ASSET_NAMES)
        self.assertIn(p.STARTER, p.ASSET_NAMES)
        self.assertIn(p.UPDATE, p.ASSET_NAMES)
        self.assertIn(p.SOURCES, p.ASSET_NAMES)

if __name__ == '__main__':
    unittest.main(verbosity=2)
