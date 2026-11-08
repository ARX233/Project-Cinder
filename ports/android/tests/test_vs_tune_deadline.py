#!/usr/bin/env python3
"""Deadline parity for the embedded and standalone WVS4 authorities."""
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import vs_server as vs


class TuneDeadlineTest(unittest.TestCase):
    def test_embedded_authority_and_client(self):
        with tempfile.TemporaryDirectory() as output:
            executable = pathlib.Path(output) / 'vs_tune_deadline'
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=undefined', '-Isrc', 'tests/vs_tune_deadline_host.c',
                            'src/vs_session.c', '-o', str(executable)], cwd=ROOT, check=True)
            subprocess.run([executable], check=True)

    def test_standalone_authority(self):
        identity = bytes(17) + b'C\4'
        for late_ready in (False, True):
            with self.subTest(late_ready=late_ready):
                server = vs.Authority(now=200)
                server.phase, server.round, server.song = vs.TUNE, 1, 3
                for i in range(3):
                    server.members.append(vs.Member(i+1, bytes([i+1])*16, ('127.0.0.1', 41000+i),
                                                    b'A'+bytes(15), 24, 10, identity, 200))

                def command(i, op, sequence, at=200, power=None, invalid=False):
                    profile = bytes(21) if power is None else (
                        identity[:2] + bytes([invalid, power, 34-power]) + identity[3:])
                    body = struct.pack('!BBHQBBBB', op, 0, 0, server.event, 0, 0, 0, 0) + profile + bytes(3)
                    member = server.members[i]
                    packet = vs.Packet(vs.COMMAND, server.incarnation, server.membership, server.round,
                                       server.config, member.id, member.session, sequence, server.term, body)
                    return server.receive(packet.encode(), member.address, at)

                def remaining(outputs):
                    self.assertEqual(len(outputs), 3)
                    return struct.unpack_from('!H', vs.decode(outputs[0][1]).body, 36+61)[0]

                self.assertFalse(command(0, vs.TUNE_DRAFT, 1, power=19))
                self.assertFalse(command(0, vs.TUNE_DRAFT, 3, power=21))
                self.assertFalse(command(0, vs.TUNE_DRAFT, 2, power=20))
                self.assertFalse(command(0, vs.TUNE_DRAFT, 4, power=22, invalid=True))
                self.assertFalse(command(2, vs.TUNE_DRAFT, 1, power=18))
                self.assertEqual(remaining(command(2, vs.TUNE_READY, 2, power=17)), 10000)
                for i in range(3):
                    self.assertEqual(remaining(command(i, vs.ACK, 5, 5200)), 5000)
                self.assertEqual(remaining(server.tick(10199)), 1)
                self.assertEqual(server.tuned, 4)
                outputs = command(0, vs.TUNE_READY, 6, 10200, power=23) if late_ready else server.tick(10200)
                self.assertEqual(remaining(outputs), 0)
                self.assertEqual(server.tuned, 7)
                self.assertEqual([m.profile[3:5] for m in server.members], [bytes((21,13)), bytes((24,10)), bytes((17,17))])


if __name__ == '__main__':
    unittest.main()
