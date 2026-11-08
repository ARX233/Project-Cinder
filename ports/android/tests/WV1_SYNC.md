# WV1 upstream sync: network tests and limitations

The Android network client, embedded host and Python server were originally synced from upstream commit 76e1558. **The current Android client and host are no longer byte-for-byte copies of that baseline**: local changes add strict lobby/GO validation, bounded receive work, optional profile-based recovery and local-host round handling. The packet wire version remains WV1, incompatible with WV2. The optional recovery profiles below do not make this a WV2 implementation.

The retained `test_vs_v2_udp.py`, `test_wv2_client_integration.py`, `wv2_client_stubs.c`, `test_vs_abort_app_host.py`, and other WV2-specific fixtures describe the old WV2 implementation and **are not applicable to the synced WV1 code**. The older `test_junction_app_car_host.py` also hard-codes WV2 abort hooks and cannot run unchanged; separate junction UI and barrier tests still run. The WV2 abort case in `test_story_goal_freeze_host.py` is explicitly skipped under WV1, while its close and story cases remain active. These historical fixtures are not evidence of WV1 functionality.

Run the local embedded-host smoke test from the repository root:

```sh
cc -std=c11 -Iports/android/src ports/android/test/net_protocol_v1_test.c \
  ports/android/src/net.c ports/android/src/vs_host.c -o /tmp/net_protocol_v1_test
/tmp/net_protocol_v1_test
```

To test the upstream Python server instead, run `python3 ports/android/tools/vs_server.py` in a separate terminal and then run `/tmp/net_protocol_v1_test server`; stop the server afterward. Both tests bind UDP 27015 and need it free. They check two-player HELLO/LOBBY, START/GO and race relay, plus WV2 discovery rejection; the embedded-host test also checks WV1 discovery. GameKit is stubbed; these tests do not exercise Android, actual Wi-Fi, packet loss, timing races or hostile traffic.

## Current optional Android recovery

Base WV1 still has no authenticated session identity, reliable delivery, round-cancel acknowledgement, or atomic result commit. Updated Android peers advertise an optional RFR1 profile after the original 21-byte car profile: flags NORMAL/ABORT/FINISHED, race ID, room-session nonce and sequence. The optional RDY1 tail brings the profile to 47 bytes. These fields isolate observed claims by session/race/sequence; they are not authentication. A 21-byte legacy peer does not gain recovery or reliable cancellation by joining an upgraded room.

The Android app uses strict slot-indexed lobby snapshots, receive-drain checks and a frozen GO roster. Matching observed ABORT claims are retained in bounded sticky history even if a newer NORMAL arrives in the same poll. History exhaustion or unverified state fails closed rather than silently discarding cancellation evidence. Missing-member recovery needs distinct accepted snapshots and its configured grace period; a receipt counter is not a server sequence or proof against replay.

The upgraded local host freezes an exact round and caches GO per slot. Its guest retry API can resend the same GO to eligible RFR1 guests every two seconds, up to 30 seconds after the first START, once the owner has accepted. This is a scoped, best-effort retry, not a WV1 delivery acknowledgement or guaranteed delivery. The original three-send behaviour for legacy GO does not by itself make retransmission reliable. A lost or unreachable host cannot preserve its room; a legacy peer may remain in the old race. The current policy does not forcibly kick legacy peers solely for lacking the extension.

FINISHED coordination prevents some premature local result processing, but **does not provide distributed atomic scoring or roll back an already processed result**. A later abort after local processing is labelled `LOCAL RESULT PROCESSED`; it is not a durable-save guarantee. Neither an observed empty receive queue nor a structurally valid lobby guarantees that no newer UDP packet is in flight.

## What these changes do not fix

**The native physical-call non-return case is unresolved.** `car_update` calls the translated CSeq synchronously on the game/EGL thread. The app's pre-physics and post-physics recovery guards only execute when control reaches them. A physical call that never returns prevents that thread from performing the next poll, recovery action and swap. Socket receive budgets bound receive work, not every instruction or external call in the translated engine.

There is no production guarantee here that an arbitrary native hang can be cancelled safely without restarting. The host-only budget/poison, snapshot/reset, simulated-stack clearing and continuation experiments are not product recovery mechanisms. Restoring CPU/ESP alone does not undo prior memory or I/O effects. Moving network polling to a thread would also require ownership/synchronization for the global client, recovery observer and simulated-memory delivery. Simply withholding a physical tick until packets arrive can withhold the send/handshake work inside that same tick; it is not a proved deadlock-free replacement.

Current host tests do not establish a device hang's root cause, device performance, real rendering, durable persistence, or complete multi-device game behaviour. Do not close the native-hang issue or mark the whole recovery objective complete on the basis of those tests. No APK build, installation, device test or release is implied by a host test pass.

## Focused host-only regression checks

From `ports/android`, run the scripts individually (some historical fixtures mutate `TMPDIR` in-process). These tests compile isolated host programs; they do not build APKs. The UDP fixtures listed below use loopback and temporary ports, unlike the older manual port-27015 smoke test above.

```sh
python3 -B tests/test_vs_host_loading_match.py
python3 -B tests/test_vs_real_host_go_branch.py
python3 -B tests/test_vs_loading_udp_convergence.py
python3 -B tests/test_vs_junction_four_three_udp.py
python3 -B tests/test_vs_finished_four_three_udp.py
python3 -B tests/test_vs_finish_abort_relay_udp.py
python3 -B tests/test_vs_late_race_callback_udp.py
python3 -B tests/test_vs_result_gate_host.py
```

The source-slice fixtures have explicit boundaries: clocks, physical state, UI and storage effects may be fakes; modeled GO acceptance is not complete app startup. The FINISHED/ABORT relay fixture uses independent first-round hosts for its four cases, not a proof of later-round isolation. The stale-RACE callback fixture injects from the host's bound socket directly, not through the host's peer-RACE relay. A callback capture proves transport delivery/rejection to that boundary, not the real vehicle state. Read each fixture's header and assertions before extending its claim to another path. Existing test passes must not be combined into a claim that an untested complete app frame or a post-result/late-ABORT scenario ran.
