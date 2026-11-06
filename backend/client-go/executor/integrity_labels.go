package executor

// integrityLabelFromRID uses the same exact RID categories as Python win_util.py.
func integrityLabelFromRID(rid uint32) string {
	switch rid {
	case 0x0000:
		return "Untrusted"
	case 0x1000:
		return "Low"
	case 0x2000:
		return "Medium"
	case 0x2100:
		return "Medium High"
	case 0x3000:
		return "High"
	case 0x4000:
		return "System"
	case 0x5000:
		return "Protected"
	default:
		return "Unknown"
	}
}
