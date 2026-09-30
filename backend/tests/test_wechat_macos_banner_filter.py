import unittest

from server.resources.jobs.wechat_macos_message_event import (
    _banner_preview,
    _is_wechat_banner_source,
)


class WeChatMacosBannerFilterTests(unittest.TestCase):
    def test_exact_wechat_source_is_accepted(self):
        self.assertTrue(_is_wechat_banner_source(['WeChat', 'Alice', 'hello']))
        self.assertTrue(_is_wechat_banner_source(['微信', 'Alice', 'hello']))
        self.assertTrue(_is_wechat_banner_source(['com.tencent.xinwechat', 'Alice', 'hello']))

    def test_rch_notifications_that_only_contain_wechat_are_rejected(self):
        self.assertFalse(_is_wechat_banner_source([
            'Device Event',
            'flcMacBook-Air.local · WeChat unread messages: 1',
        ]))
        self.assertFalse(_is_wechat_banner_source([
            'Background Job Started',
            'wechat_macos_message_event#c9111194 started on flcMacBook-Air.local',
        ]))
        self.assertFalse(_is_wechat_banner_source([
            'flcMacBook-Air.local · WeChat notification received: Hide Details',
        ]))

    def test_notification_center_detail_controls_are_not_message_preview(self):
        self.assertEqual('', _banner_preview(['WeChat', 'Show Details']))
        self.assertEqual('', _banner_preview(['WeChat', 'Hide Details']))
        self.assertEqual('hello', _banner_preview(['WeChat', 'hello', 'Hide Details']))


if __name__ == '__main__':
    unittest.main()
