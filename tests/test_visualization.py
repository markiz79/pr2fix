import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as elementtree

from src.main import main
from src.visualization import mermaid_text, save_graph, svg_text


ROOT = Path(__file__).resolve().parents[1]
NS = {'s': 'http://www.w3.org/2000/svg'}


class VisualizationTests(unittest.TestCase):
    def test_mermaid_cycle_and_boundary(self):
        graph = {'A': ['B', 'C'], 'B': ['A'], 'C': None}
        text = mermaid_text(graph)
        self.assertIn('n0["A"]', text)
        self.assertIn('n0 --> n1', text)
        self.assertIn('n1 --> n0', text)
        self.assertIn('class n2 boundary', text)
        self.assertEqual(text.count(' --> '), 3)

    def test_mermaid_safe_labels(self):
        text = mermaid_text({'end': ['x"<&'], 'x"<&': []})
        self.assertIn('n0["end"]', text)
        self.assertNotIn('x"<&', text)
        self.assertIn('#34;', text)

    def test_svg_preserves_graph(self):
        graph = {'A': ['B', 'C'], 'B': ['D'], 'C': ['D'], 'D': ['A']}
        root = elementtree.fromstring(svg_text(graph))
        nodes = {item.attrib['data-package'] for item in
                 root.findall('s:g', NS)}
        edges = {(item.attrib['data-source'], item.attrib['data-target'])
                 for item in root.findall('s:path', NS)}
        self.assertEqual(nodes, set(graph))
        self.assertEqual(edges, {('A', 'B'), ('A', 'C'), ('B', 'D'),
                                 ('C', 'D'), ('D', 'A')})

    def test_single_boundary_node(self):
        root = elementtree.fromstring(svg_text({'A': None}))
        rect = root.find('s:g/s:rect', NS)
        self.assertEqual(rect.attrib['stroke-dasharray'], '5 5')
        self.assertEqual(root.findall('s:path', NS), [])

    def test_leaf_is_not_boundary(self):
        root = elementtree.fromstring(svg_text({'A': []}))
        self.assertNotIn('stroke-dasharray',
                         root.find('s:g/s:rect', NS).attrib)

    def test_self_loop(self):
        root = elementtree.fromstring(svg_text({'A': ['A']}))
        edge = root.find('s:path', NS)
        self.assertEqual(edge.attrib['data-source'], 'A')
        self.assertEqual(edge.attrib['data-target'], 'A')
        self.assertIn('C', edge.attrib['d'])

    def test_xml_escaping(self):
        name = 'A<&"'
        root = elementtree.fromstring(svg_text({name: []}))
        self.assertEqual(root.find('s:g/s:text', NS).text, name)

    def test_save_both_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'graph.svg'
            save_graph({'A': []}, path)
            self.assertIn('flowchart LR',
                          path.with_suffix('.mmd').read_text())
            self.assertEqual(elementtree.parse(path).getroot().tag,
                             '{http://www.w3.org/2000/svg}svg')

    def test_cli_creates_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'repo.txt').write_text('A: B\nB: A\n')
            (path / 'config.toml').write_text(
                'package="A"\nrepository="repo.txt"\ntest_mode=true\n'
                'output="graph.svg"\nmax_depth=2\n'
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / 'src/main.py'),
                 str(path / 'config.toml')], cwd=folder,
                capture_output=True, text=True, encoding='utf-8',
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((path / 'graph.svg').is_file())
            self.assertTrue((path / 'graph.mmd').is_file())
            self.assertIn('SVG:', result.stdout)

    def test_cli_write_error(self):
        with patch('sys.argv', ['main.py', str(ROOT / 'config.toml')]):
            with patch('src.main.analyze', return_value={'A': []}):
                with patch('src.main.save_graph', side_effect=OSError('x')):
                    error = io.StringIO()
                    with redirect_stdout(io.StringIO()):
                        with redirect_stderr(error):
                            self.assertEqual(main(), 1)
                    self.assertIn('Ошибка:', error.getvalue())

    def test_default_config_from_other_directory(self):
        original = Path.cwd()
        self.addCleanup(os.chdir, original)
        with tempfile.TemporaryDirectory() as folder:
            os.chdir(folder)
            with patch('sys.argv', ['main.py']):
                with patch('src.main.analyze', return_value={'A': []}):
                    with patch('src.main.save_graph') as save:
                        with redirect_stdout(io.StringIO()):
                            self.assertEqual(main(), 0)
                        self.assertEqual(save.call_args.args[1],
                                         ROOT / 'graph.svg')
            os.chdir(original)

    def test_reverse_does_not_save_image(self):
        args = ['main.py', str(ROOT / 'examples/test.toml'),
                '--reverse', 'D']
        with patch('sys.argv', args):
            with patch('src.main.save_graph') as save:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
                save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
