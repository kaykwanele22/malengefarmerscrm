import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent

class MobileResponsiveRegressionTests(unittest.TestCase):
    def test_base_loads_mobile_css(self):
        text=(ROOT/"templates"/"base.html").read_text(encoding="utf-8")
        self.assertIn("css/mobile.css", text)
    def test_mobile_navigation_hooks_exist(self):
        text=(ROOT/"templates"/"base.html").read_text(encoding="utf-8")
        for token in ['id="mobileMenuButton"','id="crmSidebar"','id="mobileSidebarOverlay"',"makeTablesResponsive"]:
            self.assertIn(token,text)
    def test_viewport_meta_exists(self):
        text=(ROOT/"templates"/"base.html").read_text(encoding="utf-8")
        self.assertIn('name="viewport"', text)
    def test_breakpoints_exist(self):
        css=(ROOT/"static"/"css"/"mobile.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width:1024px)",css)
        self.assertIn("@media (max-width:700px)",css)
        self.assertIn("content:attr(data-label)",css)

if __name__=="__main__":
    unittest.main(verbosity=2)
