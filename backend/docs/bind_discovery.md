# LAN Bind discovery

The Server's **Connect to Client → Discovery** tab finds Python Bind Clients on the selected Server network interface. **Scan** sends one UDP broadcast to port `19449` and collects replies for approximately two seconds. Each result contains the source IP address, Bind TCP port, hostname, operating system, transport (`tcp` / `mtls_tcp`), and whether a main connection can currently be accepted.

Bind Clients that listen on a non-loopback address advertise while their Bind TCP listener is running. This uses a separate UDP socket and does not create an RCH session. Set `"bind_discovery_enabled": false` in the Client's JSON profile to suppress discovery responses. Clients listening only on loopback do not advertise. When several independent Bind Client processes run on one host, one process answers UDP discovery requests and the others register their listening ports over loopback. If that process exits, a remaining Bind process takes over; crashed registrations expire automatically. Bind TCP continues working even if UDP discovery is unavailable.

The Server enumerates its active IPv4 interfaces. The administrator chooses the interface, clicks **Scan**, selects a result, and uses the existing **Save** or **Connect** action. Device records are not persisted by scanning; saving/connecting follows the existing Saved Bind Targets workflow. **Manual** retains the existing address/port form.

Replies are untrusted LAN discovery data. mTLS connection authentication still occurs through the established Bind connector, and discovery does not bypass the configured transport. Broadcast discovery normally stays within one LAN broadcast domain; firewalls, VPNs, and Wi-Fi client isolation can block packets.
