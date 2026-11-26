"""
test_node_ctl.py - unit tests for scripts/node_ctl.py (subprocess mocked)
plus static checks of the node setup PowerShell scripts.
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import node_ctl  # noqa: E402

SHA = "a" * 40


def _ok(stdout: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr="")


class ValidationTests(unittest.TestCase):
    def test_host_valid(self):
        for h in ("lca-node", "10.42.0.2", "node-b.local", "lcaops@10.42.0.2"):
            self.assertEqual(node_ctl.validate_host(h), h)

    def test_host_injection_rejected(self):
        bad = ["a;b", "a b", "-oProxyCommand=calc", "a|b", "a&b", "$(x)", "a`b",
               "", "a\nb", "@host", "user@", "-Sfoo@h", "-oX@h", ".u@h", "a/b", "a\\b", "x" * 300]
        for h in bad:
            with self.assertRaises(node_ctl.NodeCtlError, msg=h):
                node_ctl.validate_host(h)

    def test_model_allowlist(self):
        for m in ("qwen2.5-coder:0.5b", "qwen2.5-coder:1.5b", "qwen2.5:1.5b"):
            self.assertEqual(node_ctl.validate_model(m), m)
        for m in ("llama3:70b", "qwen2.5:1.5b; rm -rf /", "", "QWEN2.5:1.5B"):
            with self.assertRaises(node_ctl.NodeCtlError):
                node_ctl.validate_model(m)

    def test_remote_path(self):
        self.assertEqual(node_ctl.validate_remote_path("C:/lca/repo"), "C:/lca/repo")
        self.assertEqual(node_ctl.validate_remote_path("D:\\lca\\repo"), "D:/lca/repo")
        bad = ["C:/lca/../Windows", "..", "relative/path", "C:/a;b", "C:/a b",
               "C:/a'b", "C:/a$b", "\\\\server\\share", "C:/a`b", ""]
        for p in bad:
            with self.assertRaises(node_ctl.NodeCtlError, msg=p):
                node_ctl.validate_remote_path(p)

    def test_lines_and_sha(self):
        self.assertEqual(node_ctl.validate_lines(200), 200)
        for n in (0, -1, 100000):
            with self.assertRaises(node_ctl.NodeCtlError):
                node_ctl.validate_lines(n)
        self.assertEqual(node_ctl.validate_sha(SHA), SHA)
        with self.assertRaises(node_ctl.NodeCtlError):
            node_ctl.validate_sha("abc;rm")

    def test_cli_rejects_bad_model_before_ssh(self):
        with mock.patch.object(node_ctl.subprocess, "run") as run:
            rc = node_ctl.main(["pull-model", "evil:7b"])
        self.assertEqual(rc, 2)
        run.assert_not_called()

    def test_cli_rejects_bad_host_before_ssh(self):
        with mock.patch.object(node_ctl.subprocess, "run") as run:
            rc = node_ctl.main(["--host", "a;b", "status"])
        self.assertEqual(rc, 2)
        run.assert_not_called()


class CommandConstructionTests(unittest.TestCase):
    def test_ssh_cmd_is_list_with_batchmode(self):
        cmd = node_ctl.ssh_cmd("lca-node", "hostname")
        self.assertIsInstance(cmd, list)
        self.assertEqual(cmd[0], "ssh")
        self.assertIn("BatchMode=yes", cmd)
        self.assertIn("--", cmd)
        self.assertEqual(cmd[-2:], ["lca-node", "hostname"])

    def test_run_uses_no_shell_and_timeout(self):
        with mock.patch.object(node_ctl.subprocess, "run", return_value=_ok("x")) as run:
            node_ctl.run(["ssh", "h", "hostname"], timeout=7)
        kwargs = run.call_args.kwargs
        self.assertFalse(kwargs.get("shell", False))
        self.assertEqual(kwargs["timeout"], 7)
        self.assertIsInstance(run.call_args.args[0], list)

    def test_pull_model_command(self):
        with mock.patch.object(node_ctl.subprocess, "run", return_value=_ok("ok")) as run:
            node_ctl.cmd_pull_model("lca-node", "qwen2.5:1.5b")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[-1], "ollama pull qwen2.5:1.5b")
        self.assertGreaterEqual(run.call_args.kwargs["timeout"], 600)

    def test_start_stop_use_scheduled_task(self):
        with mock.patch.object(node_ctl.subprocess, "run", return_value=_ok()) as run:
            node_ctl.cmd_start("lca-node")
            node_ctl.cmd_stop("lca-node")
        start_remote = run.call_args_list[0].args[0][-1]
        stop_remote = run.call_args_list[1].args[0][-1]
        self.assertIn("Start-ScheduledTask", start_remote)
        self.assertIn("'LCA Server'", start_remote)
        self.assertIn("Stop-ScheduledTask", stop_remote)
        self.assertIn("server.pid", stop_remote)
        self.assertNotIn("Get-Process python", stop_remote)

    def test_logs_command(self):
        with mock.patch.object(node_ctl.subprocess, "run", return_value=_ok("line")) as run:
            node_ctl.cmd_logs("lca-node", 50)
        remote = run.call_args.args[0][-1]
        self.assertIn("-Tail 50", remote)
        self.assertIn("C:/lca/logs", remote)

    def test_deploy_sequence(self):
        outputs = [_ok(SHA + "\n"), _ok(), _ok(), _ok("PREV=" + "b" * 40 + "\nDEPLOYED=" + SHA)]
        with mock.patch.object(node_ctl.subprocess, "run", side_effect=outputs) as run:
            node_ctl.cmd_deploy("lca-node", "C:/lca/repo", Path("."))
        cmds = [c.args[0] for c in run.call_args_list]
        self.assertEqual(cmds[0][:2], ["git", "-C"])
        self.assertIn("rev-parse", cmds[0])
        self.assertIn("bundle", cmds[1])
        self.assertEqual(cmds[2][0], "scp")
        self.assertTrue(cmds[2][-1].startswith("lca-node:C:/lca/inbox/lca-" + SHA))
        remote = cmds[3][-1]
        self.assertIn("fetch", remote)
        self.assertIn("checkout --detach " + SHA, remote)
        self.assertNotIn("reset --hard", remote)
        self.assertNotIn("https://", remote)

    def test_restart_waits_for_health(self):
        with mock.patch.object(node_ctl, "cmd_stop") as stop, \
             mock.patch.object(node_ctl, "cmd_start") as start, \
             mock.patch.object(node_ctl, "remote_health", side_effect=[None, {"ok": True}]), \
             mock.patch.object(node_ctl.time, "sleep"):
            result = node_ctl.cmd_restart("lca-node", wait_s=10)
        stop.assert_called_once()
        start.assert_called_once()
        self.assertTrue(result["ok"])


class ErrorHandlingTests(unittest.TestCase):
    def test_timeout_is_thai_error(self):
        exc = subprocess.TimeoutExpired(cmd=["ssh"], timeout=5)
        with mock.patch.object(node_ctl.subprocess, "run", side_effect=exc):
            with self.assertRaises(node_ctl.NodeCtlError) as ctx:
                node_ctl.run(["ssh", "h", "hostname"], timeout=5)
        self.assertIn("หมดเวลา", str(ctx.exception))

    def test_missing_binary_is_thai_error(self):
        with mock.patch.object(node_ctl.subprocess, "run", side_effect=FileNotFoundError()):
            with self.assertRaises(node_ctl.NodeCtlError) as ctx:
                node_ctl.run(["ssh", "h", "hostname"], timeout=5)
        self.assertIn("ไม่พบโปรแกรม", str(ctx.exception))

    def test_status_unreachable(self):
        with mock.patch.object(node_ctl.subprocess, "run", return_value=_ok("", rc=255)):
            st = node_ctl.cmd_status("lca-node")
        self.assertFalse(st["ssh"])

    def test_status_parses_values(self):
        outs = [_ok("NODE-B\n"), _ok('{"ok": true, "ollama": "up"}'),
                _ok("4194304\n"), _ok("NAME ID\nqwen2.5:1.5b x\n")]
        with mock.patch.object(node_ctl.subprocess, "run", side_effect=outs):
            st = node_ctl.cmd_status("lca-node")
        self.assertTrue(st["ssh"])
        self.assertTrue(st["health"]["ok"])
        self.assertEqual(st["ram_free_mb"], 4096)
        self.assertIn("qwen2.5:1.5b", st["ollama"])

    def test_redact_hides_tokens(self):
        txt = "LCA_TOKEN=abcdefSECRET X-Auth-Token: zzzSECRET"
        out = node_ctl.redact(txt)
        self.assertNotIn("SECRET", out)

    def test_main_prints_redacted(self):
        with mock.patch.object(node_ctl.subprocess, "run",
                               return_value=_ok("LCA_TOKEN=topSECRET\n")), \
             mock.patch("builtins.print") as pr:
            node_ctl.main(["logs", "--lines", "5"])
        printed = " ".join(str(a) for c in pr.call_args_list for a in c.args)
        self.assertNotIn("topSECRET", printed)


class PowerShellStaticTests(unittest.TestCase):
    server = (ROOT / "scripts" / "node_setup_server.ps1").read_text(encoding="utf-8")
    client = (ROOT / "scripts" / "node_setup_client.ps1").read_text(encoding="utf-8")

    def test_key_only_auth(self):
        self.assertIn("PasswordAuthentication no", self.server)
        self.assertIn("PubkeyAuthentication yes", self.server)
        self.assertIn("KbdInteractiveAuthentication no", self.server)

    def test_public_key_is_parameter_not_generated(self):
        self.assertRegex(self.server, r"\[Parameter\(Mandatory[^\]]*\)\]\s*\[string\]\$PublicKey")
        self.assertNotIn("ssh-keygen -t", self.server)

    def test_firewall_remote_address(self):
        rules = re.findall(r"New-NetFirewallRule[^\n]*", self.server)
        self.assertTrue(rules)
        for r in rules:
            self.assertIn("-RemoteAddress", r)
        self.assertNotIn("11434", "".join(rules))

    def test_backup_before_edit(self):
        backup = self.server.find("Copy-Item -LiteralPath $SshdConfig")
        write = self.server.find("Set-Content -LiteralPath $SshdConfig")
        self.assertGreater(backup, 0)
        self.assertGreater(write, backup)

    def test_ip_change_dry_run_default(self):
        for src in (self.server, self.client):
            self.assertIn("[switch]$ApplyNetwork", src)
            self.assertIn("SupportsShouldProcess", src)
            idx = src.find("New-NetIPAddress")
            self.assertGreater(idx, 0)
            guard = src.rfind("if (-not $ApplyNetwork)", 0, idx)
            self.assertGreater(guard, 0)
            self.assertNotIn("-DefaultGateway", src)

    def test_scheduled_task_and_no_token_in_args(self):
        self.assertIn("'LCA Server'", self.server)
        self.assertIn("Register-ScheduledTask", self.server)
        self.assertIn("token.txt", self.server)
        self.assertNotRegex(self.server, r"--token")

    def test_sshd_stopped_until_configured(self):
        main = self.server[self.server.find("# ---------- main"):]
        self.assertNotIn("Start-Service sshd", self.server[:self.server.find("# ---------- main")])
        self.assertNotIn("Restart-Service sshd", self.server)
        start = main.find("Start-Service sshd")
        for step in ("Install-Sshd", "Set-SshdConfig", "Install-PublicKey", "Set-LcaFirewall"):
            self.assertLess(main.find(step), start, step)
        self.assertIn("finally", main)
        self.assertGreater(main.find("Stop-Service sshd", main.find("finally")), 0)
        inst = self.server[self.server.find("function Install-Sshd"):self.server.find("function Get-NewSshdConfig")]
        self.assertIn("Stop-Service sshd", inst)

    def test_adapter_guard_before_ip_change(self):
        for src in (self.server, self.client):
            self.assertIn("[switch]$AllowDefaultRouteAdapter", src)
            self.assertIn("-DestinationPrefix '0.0.0.0/0' -InterfaceAlias $Adapter", src)
            self.assertIn(r"802\.11", src)
            fn = src[src.find("function Set-CableIp"):]
            self.assertLess(fn.find("Assert-CableAdapter"), fn.find("Set-NetIPInterface"))

    def test_listen_address_and_firewall_interface(self):
        self.assertRegex(self.server, r"\[Parameter\(Mandatory[^\]]*\)\]\s*\[string\]\$Adapter")
        self.assertIn("ListenAddress $ListenIp", self.server)
        self.assertIn("Get-NewSshdConfig $old (Get-ListenIp)", self.server)
        ssh_rule = [r for r in re.findall(r"New-NetFirewallRule[^\n]*", self.server) if "LCA-SSH" in r][0]
        self.assertIn("-InterfaceAlias $Adapter", ssh_rule)

    def test_match_first_line_and_key_replace(self):
        self.assertIn("if ($idx -eq 1) { return @($block) + @($out) }", self.server)
        fn = self.server[self.server.find("function Install-PublicKey"):self.server.find("function Set-LcaFirewall")]
        self.assertIn("from=`\"$ClientIp`\",*", fn)
        self.assertLess(fn.find("Copy-Item"), fn.find("Set-Content"))

    def test_scp_has_double_dash(self):
        src = (ROOT / "scripts" / "node_ctl.py").read_text(encoding="utf-8")
        self.assertIn('"scp", "-q", "-o", "BatchMode=yes", "--",', src)

    def test_client_writes_host_entry_and_key(self):
        self.assertIn("lca_node_ed25519", self.client)
        self.assertIn("Host lca-node", self.client)
        self.assertIn("StrictHostKeyChecking", self.client)
        self.assertIn("Copy-Item", self.client)


if __name__ == "__main__":
    unittest.main()
