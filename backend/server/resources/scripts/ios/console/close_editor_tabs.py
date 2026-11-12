SCRIPT_METADATA = {
    "name": "ios/console/close_editor_tabs",
    "display_name": "Close Editor Tabs",
    "description": "Close all open text editor tabs in Pythonista",
    "platforms": ["ios"],
    "category": "Console",
    "params": []
}

from objc_util import *

@on_main_thread
def main():
	win = UIApplication.sharedApplication().keyWindow()
	root_vc = win.rootViewController()
	if root_vc.isKindOfClass_(ObjCClass('PASlidingContainerViewController')):
		tabs_vc = root_vc.detailViewController()
		for tab in tabs_vc.tabViewControllers():
			if tab.isKindOfClass_(ObjCClass('PA2UniversalTextEditorViewController')):
				tabs_vc.closeTab_(tab)  

if __name__ == '__main__':
	main()
