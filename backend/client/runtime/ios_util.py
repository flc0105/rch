import os
import time

from core.platform.platform_identity import detect_platform_alias
from core.utils.formatting import get_size, seconds_to_readable_text, timestamp_to_readable_time

if detect_platform_alias() == 'ios':
    from objc_util import ObjCClass, ns, ObjCInstance


def _safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default



def get_ios_username():
    for key in ('USER', 'LOGNAME', 'USERNAME'):
        value = os.environ.get(key)
        if value:
            return value
    return _safe_call(os.getlogin, 'unknown')


def get_ios_process_info():
    info = {
        'process_name': None,
        'process_id': None,
        'username': None,
        'arguments': None,
        'processor_count': None,
        'physical_memory': None,
        'physical_memory_bytes': None,
        'system_boot_time': None,
        'system_uptime': None,
        'system_uptime_seconds': None,
        'operating_system_version_string': None,
        'low_power_mode_enabled': None,
    }

    try:
        NSProcessInfo = ObjCClass('NSProcessInfo')
        proc = NSProcessInfo.processInfo()
        info['process_name'] = _safe_call(lambda: str(proc.processName()))
        info['process_id'] = _safe_call(lambda: int(proc.processIdentifier()))
        info['username'] = _safe_call(lambda: str(proc.userName()))
        info['arguments'] = _safe_call(lambda: [str(x) for x in list(proc.arguments())])
        info['processor_count'] = _safe_call(lambda: int(proc.processorCount()))
        physical_memory = _safe_call(lambda: int(proc.physicalMemory()))
        info['physical_memory_bytes'] = physical_memory
        info['physical_memory'] = get_size(physical_memory) if physical_memory is not None else None
        system_uptime = _safe_call(lambda: int(proc.systemUptime()))
        info['system_uptime_seconds'] = system_uptime
        info['system_uptime'] = seconds_to_readable_text(system_uptime) if system_uptime is not None else None
        info['system_boot_time'] = timestamp_to_readable_time(
            int(time.time() - system_uptime)) if system_uptime is not None else None
        info['operating_system_version_string'] = _safe_call(lambda: str(proc.operatingSystemVersionString()))
        info['low_power_mode_enabled'] = _safe_call(lambda: bool(proc.isLowPowerModeEnabled()))
    except Exception:
        pass

    return info


def get_ios_device_info():
    info = {
        'device_name': None,
        'device_model': None,
        'device_localized_model': None,
        'device_type': None,
        'system': None,
        'system_version': None,
        'machine_name': None,
        'hostname': None,
        'identifier_for_vendor': None,
    }

    try:
        UIDevice = ObjCClass('UIDevice')
        device = UIDevice.currentDevice()

        idiom_map = {
            0: "Phone",
            1: "Pad",
            2: "TV",
            3: "CarPlay",
            4: "Mac",
            5: "Vision",
        }

        info['device_name'] = _safe_call(lambda: str(device.name()))
        info['device_model'] = _safe_call(lambda: str(device.model()))
        info['device_localized_model'] = _safe_call(lambda: str(device.localizedModel()))
        info['system'] = _safe_call(lambda: str(device.systemName()))
        info['system_version'] = _safe_call(lambda: str(device.systemVersion()))
        info['device_type'] = _safe_call(
            lambda: idiom_map.get(int(device.userInterfaceIdiom()), str(int(device.userInterfaceIdiom()))))

        identifier_for_vendor = _safe_call(lambda: device.identifierForVendor())
        if identifier_for_vendor is not None:
            info['identifier_for_vendor'] = _safe_call(lambda: str(identifier_for_vendor.UUIDString()))
    except Exception:
        pass

    try:
        uname_info = os.uname()
        info['machine_name'] = uname_info.machine
        info['hostname'] = uname_info.nodename
    except Exception:
        pass

    return info


def get_ios_bundle_info():
    info = {
        'bundle_identifier': None,
        'bundle_path': None,
        'executable_path': None,
        'resource_path': None,
        'bundle_name': None,
        'app_name': None,
        'bundle_version': None,
        'bundle_short_version': None,
    }

    try:
        NSBundle = ObjCClass('NSBundle')
        bundle = NSBundle.mainBundle()

        info['bundle_identifier'] = _safe_call(lambda: str(bundle.bundleIdentifier()))
        info['bundle_path'] = _safe_call(lambda: str(bundle.bundlePath()))
        info['executable_path'] = _safe_call(lambda: str(bundle.executablePath()))
        info['resource_path'] = _safe_call(lambda: str(bundle.resourcePath()))

        info_dict = _safe_call(lambda: bundle.infoDictionary())
        if info_dict is not None:
            def get_value(key):
                value = info_dict.objectForKey_(key)
                return str(value) if value is not None else None

            info['bundle_name'] = _safe_call(lambda: get_value('CFBundleName'))
            info['app_name'] = _safe_call(lambda: get_value('CFBundleDisplayName')) or _safe_call(
                lambda: get_value('CFBundleName'))
            info['bundle_version'] = _safe_call(lambda: get_value('CFBundleVersion'))
            info['bundle_short_version'] = _safe_call(lambda: get_value('CFBundleShortVersionString'))
    except Exception:
        pass

    return info


def contact_to_dict(c):
    family_name = str(c.familyName() or '')
    middle_name = str(c.middleName() or '')
    given_name = str(c.givenName() or '')

    full_name = ' '.join(x for x in [family_name, middle_name, given_name] if x).strip()
    if not full_name:
        full_name = ' '.join(x for x in [given_name, middle_name, family_name] if x).strip()
    if not full_name:
        full_name = str(c.organizationName() or '').strip() or '(no name)'

    phone_numbers = []
    nums = c.phoneNumbers()
    for j in range(int(nums.count())):
        item = ObjCInstance(nums.objectAtIndex_(j))
        label = str(item.label()) if item.label() else ''
        value_obj = item.value()
        value = str(value_obj.stringValue()) if value_obj else ''
        if value:
            phone_numbers.append({
                'label': label,
                'value': value,
            })

    email_addresses = []
    emails = c.emailAddresses()
    for j in range(int(emails.count())):
        item = ObjCInstance(emails.objectAtIndex_(j))
        label = str(item.label()) if item.label() else ''
        value = str(item.value()) if item.value() else ''
        if value:
            email_addresses.append({
                'label': label,
                'value': value,
            })

    return {
        'full_name': full_name,
        'family_name': family_name,
        'middle_name': middle_name,
        'given_name': given_name,
        'organization': str(c.organizationName() or ''),
        'job_title': str(c.jobTitle() or ''),
        'phone': phone_numbers,
        'email': email_addresses,
    }


def get_ios_contacts():
    CNContactStore = ObjCClass('CNContactStore')
    CNContact = ObjCClass('CNContact')

    store = CNContactStore.alloc().init()

    keys = ns([
        'givenName',
        'familyName',
        'middleName',
        'organizationName',
        'jobTitle',
        'phoneNumbers',
        'emailAddresses',
    ])

    results = []
    seen = set()

    containers = store.containersMatchingPredicate_error_(None, None)

    for i in range(int(containers.count())):
        container = ObjCInstance(containers.objectAtIndex_(i))
        container_id = str(container.identifier())

        contacts = store.unifiedContactsMatchingPredicate_keysToFetch_error_(
            CNContact.predicateForContactsInContainerWithIdentifier_(container_id),
            keys,
            None
        )

        for j in range(int(contacts.count())):
            c = ObjCInstance(contacts.objectAtIndex_(j))
            item = contact_to_dict(c)

            uniq = (
                item['full_name'],
                tuple((x['label'], x['value']) for x in item['phone']),
                tuple((x['label'], x['value']) for x in item['email']),
            )
            if uniq in seen:
                continue
            seen.add(uniq)

            results.append(item)

    return results


def get_icloud_container_ids(info):
    containers = info.get("NSUbiquitousContainers", {})

    if isinstance(containers, dict):
        return list(containers.keys())

    return []


def read_info_plist():
    import plistlib
    NSBundle = ObjCClass("NSBundle")
    bundle_path = str(NSBundle.mainBundle().bundlePath())
    plist_path = os.path.join(bundle_path, "Info.plist")

    with open(plist_path, "rb") as f:
        return plistlib.load(f)


def get_icloud_path(info):
    NSFileManager = ObjCClass("NSFileManager")
    fm = NSFileManager.defaultManager()

    for cid in get_icloud_container_ids(info):
        try:
            url = fm.URLForUbiquityContainerIdentifier_(ns(cid))
            if url:
                return str(url.path())
        except Exception:
            pass

    try:
        url = fm.URLForUbiquityContainerIdentifier_(None)
        if url:
            return str(url.path())
    except Exception:
        pass

    return "unavailable"


def spawn(path):
    import runpy
    import sys
    import os

    def runner():
        # 很多脚本依赖当前目录找配置、模块、资源
        os.chdir(os.path.dirname(path))

        # 很多脚本依赖 sys.argv
        sys.argv = [path]

        runpy.run_path(path, run_name='__main__')

    import threading
    t = threading.Thread(
        target=runner,
        name='handoff-main-py',
        daemon=False,  # 关键：不要 daemon
    )
    t.start()
