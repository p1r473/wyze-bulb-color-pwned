# Lightjack post-loader backup

Added 2026-10-21. This read-only host tool uses the existing loader interfaces. It has passed synthetic loopback tests; it has not read a physical bulb. It does not install the loader, upload firmware, set a boot slot, restart a bulb or operate its LEDs.

## Where the backup fits

The upstream wireless method first installs `wyze-loader` into an application slot and changes OTA boot selection. Its backup endpoint becomes available after that installation. The resulting full-flash snapshot contains the loader and the unit's state at that time. It is **not an untouched factory image**. Factory-mode entry or prior pairing may also change settings. An unchanged factory snapshot would require a separately verified read-only access method before installation; this tool does not provide that method.

Keep one bulb stock. On the test bulb, identify and validate the wireless installation method, install the loader, then take and verify this snapshot before uploading the Lightjack application into the other OTA slot. That upload may replace the remaining stock application, so keep the backup private and preserve a second copy. A matching backup hash does not prove restoration works. Physical recovery still needs a controlled hardware test.

## Read the snapshot

After connecting directly to the isolated loader access point, run from the repository root with Python 3.10 or newer:

```sh
python scripts/backup_loader.py --host 192.168.4.1 --output ../private-bulb-01/post-loader
```

The destination must be new and outside this source repository. Keep it private: flash can contain Wi-Fi credentials, factory data and device identifiers. No proxy settings are used, redirects are rejected, and the tool sends only GET requests to `/info`, `/parts` and `/dump`. The loader uses unauthenticated HTTP. Confirm the intended isolated bulb network yourself; a reported MAC address is not cryptographic identity verification.

The reader checks the reported partition map against `src/wyze-loader/partitions_wyze.csv`, reads the complete 4 MiB range twice in 64 KiB chunks, requires an exact response length for every chunk, and compares SHA256 hashes. It also requires unchanged loader metadata after each pass and verifies the saved file. The fixed size is appropriate only after confirming the actual unit has the expected 4 MiB layout. No firmware write is attempted when that check fails.

Successful output is `flash.bin` plus `manifest.json` with `complete: true`, two matching read hashes and `pristine_factory_backup: false`. Treat any other state as incomplete. Failures retain the partial directory for diagnosis and never overwrite it on retry. Use a new directory for the next attempt. A backup can fail because flash changes while reading; investigate rather than bypass the comparison.

Default limits are 15 seconds per HTTP request and 600 seconds for the complete operation. `--timeout` and `--total-timeout` can be adjusted within bounded limits. A watchdog closes the socket at the request deadline, including during trickling HTTP headers. The CLI prints a nonzero exit status and a JSON error on normal failures. It never prints flash contents or the reported MAC.

## Host verification

```sh
python scripts/test_backup_loader.py
```

The seven test methods include a complete two-pass 4 MiB synthetic dump with real HTTP chunked transfer, truncated and oversized responses, changing data and identity, redirects, trickling-header timeouts, invalid layout, output-path restrictions and refusal to overwrite. Test data is synthetic and is saved under the operating system's temporary `lightjack-loader-tests` directory. Test success does not establish actual bulb reads, installer compatibility, stock restoration or hardware recovery.

The original loader and its license remain unchanged. New host code uses the repository's MIT license.
