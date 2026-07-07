import os
import unittest
from unittest.mock import MagicMock, patch

# Mock Gradio and other imports that might fail or are not needed for logic test
import sys
sys.modules['gradio'] = MagicMock()
sys.modules['github'] = MagicMock()
sys.modules['openai'] = MagicMock()
sys.modules['chevron'] = MagicMock()

# Import the functions from app.py
# We need to handle the global variables in app.py
with patch('app.gh', MagicMock()):
    import app

class TestSlidesLogic(unittest.TestCase):
    def setUp(self):
        self.repo_name = "test/repo"
        self.branch_name = "main"
        app.gh = MagicMock()
        self.mock_repo = MagicMock()
        app.gh.get_repo.return_value = self.mock_repo

    def test_get_reports_in_branch_with_slides_folder(self):
        # Mock successful detection of slides folder
        def get_contents_mock(path, ref=None):
            if path == "user_experience_reports/slides":
                return MagicMock() # directory exists
            if path == "user_experience_reports":
                mock_file = MagicMock()
                mock_file.name = "report.md"
                return [mock_file]
            raise Exception("404 Not Found")
        
        self.mock_repo.get_contents.side_effect = get_contents_mock
        
        # Mock tree for recursive scan
        mock_tree_element = MagicMock()
        mock_tree_element.type = "blob"
        mock_tree_element.path = "user_experience_reports/slides/01_intro.md"
        self.mock_repo.get_git_tree.return_value.tree = [mock_tree_element]

        reports = app.get_reports_in_branch(self.repo_name, self.branch_name, filter_type="slides")
        
        self.assertIn("user_experience_reports/slides", reports)
        # Should be at the top due to score -2000
        self.assertEqual(reports[0], "user_experience_reports/slides")

    @patch('subprocess.run')
    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('shutil.rmtree')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    def test_render_slides_merging(self, mock_open, mock_rmtree, mock_exists, mock_makedirs, mock_run):
        # Mock exists to say index.html is created
        mock_exists.side_effect = lambda p: True if "index.html" in p else False
        
        # Mock slides folder contents
        slide1 = MagicMock()
        slide1.name = "01_slide.md"
        slide1.path = "user_experience_reports/slides/01_slide.md"
        
        slide2 = MagicMock()
        slide2.name = "02_slide.md"
        slide2.path = "user_experience_reports/slides/02_slide.md"
        
        def get_contents_mock(path, ref=None):
            if path == "user_experience_reports/slides":
                return [slide1, slide2]
            if "01_slide.md" in path:
                m = MagicMock()
                m.decoded_content = b"Slide 1 Content"
                return m
            if "02_slide.md" in path:
                m = MagicMock()
                m.decoded_content = b"Slide 2 Content"
                return m
            return MagicMock()

        self.mock_repo.get_contents.side_effect = get_contents_mock
        
        # We also need to mock add_log to avoid errors if it tries to print
        with patch('app.add_log', MagicMock()):
            result = app.render_slides(self.repo_name, self.branch_name, "user_experience_reports/slides")
        
        # Verify merging logic
        mock_open.assert_any_call(unittest.mock.ANY, "w")
        handle = mock_open()
        
        # Check if Slide 1 and Slide 2 are merged with ---
        written_content = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertIn("Slide 1 Content", written_content)
        self.assertIn("Slide 2 Content", written_content)
        self.assertIn("\n\n---\n\n", written_content)
        
        # Verify IFrame URL is relative
        self.assertIn('src="file=slides_site_', result)
        self.assertNotIn('src="/file=', result)

if __name__ == "__main__":
    unittest.main()
