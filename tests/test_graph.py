import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from src.main import analyze, build_graph, dependency_names
from src.main import read_test_repository
from src.main import analyze_reverse, reverse_dependencies, reverse_graph
from src.main import main


class GraphTests(unittest.TestCase):
    def test_bfs_order_and_shared_dependency(self):
        source = {'A': ['B', 'C'], 'B': ['D'], 'C': ['D'], 'D': []}
        calls = []

        def neighbors(name):
            calls.append(name)
            return source[name]

        self.assertEqual(build_graph('A', 3, neighbors), source)
        self.assertEqual(calls, ['A', 'B', 'C', 'D'])

    def test_depth_limit(self):
        source = {'A': ['B'], 'B': ['C'], 'C': []}
        fetch = Mock(side_effect=source.__getitem__)
        self.assertEqual(build_graph('A', 1, fetch),
                         {'A': ['B'], 'B': None})
        fetch.assert_called_once_with('A')

    def test_zero_depth(self):
        fetch = Mock()
        self.assertEqual(build_graph('A', 0, fetch), {'A': None})
        fetch.assert_not_called()

    def test_cycle(self):
        source = {'A': ['B'], 'B': ['C'], 'C': ['A']}
        fetch = Mock(side_effect=source.__getitem__)
        self.assertEqual(build_graph('A', 10, fetch), source)
        self.assertEqual(fetch.call_count, len(source))

    def test_self_cycle(self):
        self.assertEqual(build_graph('A', 5, lambda name: ['A']),
                         {'A': ['A']})

    def test_empty_and_disconnected(self):
        source = {'A': [], 'B': ['C'], 'C': []}
        self.assertEqual(build_graph('A', 3, source.__getitem__), {'A': []})

    def test_shortest_depth(self):
        source = {'A': ['B', 'D'], 'B': ['C'], 'C': ['D'], 'D': ['E']}
        expected = {'A': ['B', 'D'], 'B': ['C'], 'D': ['E'],
                    'C': None, 'E': None}
        self.assertEqual(build_graph('A', 2, source.__getitem__), expected)

    def test_long_chain_without_recursion(self):
        length = 1500
        graph = build_graph(0, length, lambda value: [value + 1])
        self.assertEqual(len(graph), length + 1)
        self.assertIsNone(graph[length])

    def test_duplicate_edges(self):
        self.assertEqual(build_graph('A', 1, lambda name: ['B', 'B']),
                         {'A': ['B'], 'B': None})

    def test_dependency_names(self):
        values = ['My_Pkg>=1', 'my.pkg; extra == "test"',
                  'Other[x] @ https://example.org/pkg.whl']
        self.assertEqual(dependency_names(values), ['my-pkg', 'other'])

    def test_remote_graph(self):
        config = {'package': 'A', 'test_mode': False,
                  'repository': 'https://example.org', 'max_depth': 2}
        with patch('src.main.get_dependencies', side_effect=[['B>=1'], []]):
            self.assertEqual(analyze(config, Path('.')),
                             {'a': ['b'], 'b': []})

    def test_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'repo.txt'
            path.write_text('A: B B\nB: A\nC:\n', encoding='utf-8')
            self.assertEqual(read_test_repository(path),
                             {'A': ['B'], 'B': ['A'], 'C': []})

    def test_invalid_repository(self):
        cases = ['A B', 'A: b\nb:', 'A: B', 'A:\nA:', '1:']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'repo.txt'
            for value in cases:
                with self.subTest(value=value):
                    path.write_text(value, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        read_test_repository(path)

    def test_missing_start(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'repo.txt'
            path.write_text('B:', encoding='utf-8')
            config = {'package': 'A', 'test_mode': True,
                      'repository': 'repo.txt', 'max_depth': 1}
            with self.assertRaisesRegex(ValueError, 'отсутствует'):
                analyze(config, Path(folder))


class ReverseTests(unittest.TestCase):
    def test_direct_and_transitive(self):
        graph = {'A': ['B'], 'B': ['C'], 'C': [], 'D': []}
        self.assertEqual(reverse_dependencies(graph, 'C', 3), ['B', 'A'])

    def test_depth(self):
        graph = {'A': ['B'], 'B': ['C'], 'C': []}
        self.assertEqual(reverse_dependencies(graph, 'C', 1), ['B'])
        self.assertEqual(reverse_dependencies(graph, 'C', 0), [])

    def test_cycle(self):
        graph = {'A': ['B'], 'B': ['C'], 'C': ['A']}
        self.assertEqual(reverse_dependencies(graph, 'A', 10), ['C', 'B'])

    def test_self_cycle(self):
        self.assertEqual(reverse_dependencies({'A': ['A']}, 'A', 3), [])

    def test_shared_and_duplicate(self):
        graph = {'A': ['B', 'C'], 'B': ['D', 'D'], 'C': ['D'], 'D': []}
        self.assertEqual(reverse_dependencies(graph, 'D', 3),
                         ['B', 'C', 'A'])

    def test_no_reverse_dependencies(self):
        graph = {'A': ['B'], 'B': [], 'C': []}
        self.assertEqual(reverse_dependencies(graph, 'A', 3), [])
        self.assertEqual(reverse_dependencies(graph, 'C', 3), [])

    def test_missing(self):
        with self.assertRaisesRegex(ValueError, 'отсутствует'):
            reverse_dependencies({'A': []}, 'Z', 3)

    def test_boundary_node(self):
        graph = {'A': ['B'], 'B': None}
        self.assertEqual(reverse_graph(graph), {'A': [], 'B': ['A']})
        self.assertEqual(reverse_dependencies(graph, 'B', 2), ['A'])

    def test_whole_test_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'repo.txt'
            path.write_text('A: B\nB:\nC: B\n', encoding='utf-8')
            config = {'package': 'A', 'test_mode': True,
                      'repository': 'repo.txt', 'max_depth': 2}
            name, result = analyze_reverse(config, Path(folder), 'B')
            self.assertEqual(name, 'B')
            self.assertEqual(result, ['A', 'C'])

    def test_reuses_bfs(self):
        with patch('src.main.build_graph', return_value={'A': [], 'B': []}):
            self.assertEqual(reverse_dependencies({'A': []}, 'A', 2), ['B'])

    def test_remote_scope_and_normalization(self):
        config = {'test_mode': False, 'max_depth': 2}
        with patch('src.main.analyze', return_value={'a': ['my-pkg'],
                                                   'my-pkg': None}):
            self.assertEqual(analyze_reverse(config, Path('.'), 'My_Pkg'),
                             ('my-pkg', ['a']))

    def test_cli(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, 'src/main.py', 'examples/test.toml',
             '--reverse', 'D'], cwd=root, capture_output=True,
            text=True, encoding='utf-8',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-3:], ['B', 'C', 'A'])

    def test_cli_missing(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, 'src/main.py', 'examples/test.toml',
             '--reverse', 'Z'], cwd=root, capture_output=True,
            text=True, encoding='utf-8',
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('отсутствует', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_cli_remote_notice(self):
        root = Path(__file__).resolve().parents[1]
        args = ['main.py', str(root / 'config.toml'), '--reverse', 'b']
        with patch('sys.argv', args):
            graph = {'a': ['b'], 'b': []}
            with patch('src.main.analyze', return_value=graph):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(), 0)
        self.assertIn('не весь репозиторий PyPI', output.getvalue())


if __name__ == '__main__':
    unittest.main()
