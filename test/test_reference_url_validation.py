import importlib.util
import ipaddress
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest import mock


def load_timeline_module():
    requests = types.ModuleType("requests")
    requests.RequestException = Exception
    yt_dlp = types.ModuleType("yt_dlp")
    yt_dlp.YoutubeDL = object
    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = object
    pydantic.ConfigDict = dict
    pydantic.Field = lambda *args, **kwargs: None
    sys.modules.setdefault("requests", requests)
    sys.modules.setdefault("yt_dlp", yt_dlp)
    sys.modules.setdefault("pydantic", pydantic)
    source = Path(__file__).parents[1] / "src" / "code" / "Timeline.py"
    source_dir = str(source.parent)
    sys.path.insert(0, source_dir)
    try:
        spec = importlib.util.spec_from_file_location("timeline_reference_validation", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def dns_answer(address):
    parsed = ipaddress.ip_address(address)
    if parsed.version == 4:
        sockaddr = (str(parsed), 443)
        family = socket.AF_INET
    else:
        sockaddr = (str(parsed), 443, 0, 0)
        family = socket.AF_INET6
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]


def make_response(status_code=200, *, headers=None, body=b"ok"):
    response = types.SimpleNamespace(
        status_code=status_code,
        headers=headers or {"Content-Type": "text/plain"},
        is_redirect=status_code in {301, 302, 303, 307, 308},
    )
    response.iter_content = lambda chunk_size: [body]
    response.close = mock.Mock()
    return response


class ReferenceURLValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.timeline = load_timeline_module()

    def test_non_global_ip_literals_are_blocked(self):
        for address in (
            "127.0.0.1",
            "10.1.2.3",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.1.1",
            "100.64.0.1",
            "100.127.255.254",
        ):
            with self.subTest(address=address):
                self.assertFalse(self.timeline._is_public_reference_host(address))

    def test_global_ipv4_and_ipv6_literals_are_allowed(self):
        self.assertTrue(self.timeline._is_public_reference_host("8.8.8.8"))
        self.assertTrue(self.timeline._is_public_reference_host("2001:4860:4860::8888"))

    def test_multicast_is_blocked_even_when_ipaddress_marks_it_global(self):
        self.assertFalse(self.timeline._is_public_reference_host("224.0.0.1"))
        self.assertFalse(self.timeline._is_public_reference_host("ff02::1"))

    def test_localhost_and_local_suffix_are_blocked_without_dns(self):
        with mock.patch.object(self.timeline.socket, "getaddrinfo") as getaddrinfo:
            self.assertFalse(self.timeline._is_public_reference_host("localhost"))
            self.assertFalse(self.timeline._is_public_reference_host("service.local"))
        getaddrinfo.assert_not_called()

    def test_hostname_resolving_to_non_global_address_is_blocked(self):
        with mock.patch.object(self.timeline.socket, "getaddrinfo", return_value=dns_answer("100.64.0.1")):
            self.assertFalse(self.timeline._is_public_reference_host("cgnat.example"))

    def test_mixed_global_and_non_global_dns_answers_are_blocked(self):
        answers = dns_answer("8.8.8.8") + dns_answer("192.168.1.10")
        with mock.patch.object(self.timeline.socket, "getaddrinfo", return_value=answers):
            self.assertFalse(self.timeline._is_public_reference_host("mixed.example"))

    def test_all_global_dns_answers_are_allowed(self):
        answers = dns_answer("8.8.8.8") + dns_answer("2001:4860:4860::8888")
        with mock.patch.object(self.timeline.socket, "getaddrinfo", return_value=answers):
            self.assertTrue(self.timeline._is_public_reference_host("global.example"))

    def test_dns_failure_and_empty_answer_are_blocked(self):
        with mock.patch.object(self.timeline.socket, "getaddrinfo", side_effect=socket.gaierror("lookup failed")):
            self.assertFalse(self.timeline._is_public_reference_host("missing.example"))
        with mock.patch.object(self.timeline.socket, "getaddrinfo", return_value=[]):
            self.assertFalse(self.timeline._is_public_reference_host("empty.example"))

    def test_both_fetch_paths_block_private_redirect_before_next_request(self):
        for fetch in (self.timeline._read_reference_url, self.timeline._fetch_reference_url):
            with self.subTest(fetch=fetch.__name__):
                redirect = make_response(302, headers={"Location": "http://private.example/admin"})

                def resolve(hostname, *args, **kwargs):
                    if hostname == "allowed.example":
                        return dns_answer("8.8.8.8")
                    if hostname == "private.example":
                        return dns_answer("10.0.0.1")
                    self.fail(f"Unexpected hostname lookup: {hostname}")

                with mock.patch.object(self.timeline.socket, "getaddrinfo", side_effect=resolve), \
                     mock.patch.object(self.timeline.requests, "get", return_value=redirect, create=True) as get:
                    result = fetch("https://allowed.example/start")

                get.assert_called_once()
                self.assertFalse(get.call_args.kwargs["allow_redirects"])
                if fetch is self.timeline._read_reference_url:
                    self.assertEqual("", result)
                else:
                    self.assertEqual((0, "", {}), result)

    def test_relative_multi_hop_redirect_validates_every_target(self):
        expected_urls = [
            "https://allowed.example/start",
            "https://allowed.example/middle/page",
            "https://allowed.example/final",
        ]
        for fetch in (self.timeline._read_reference_url, self.timeline._fetch_reference_url):
            with self.subTest(fetch=fetch.__name__):
                responses = [
                    make_response(302, headers={"Location": "middle/page"}),
                    make_response(307, headers={"Location": "../final"}),
                    make_response(200, body=b"final body"),
                ]
                with mock.patch.object(self.timeline.socket, "getaddrinfo", return_value=dns_answer("8.8.8.8")) as dns, \
                     mock.patch.object(self.timeline.requests, "get", side_effect=responses, create=True) as get, \
                     mock.patch.object(self.timeline, "_validate_reference_url", wraps=self.timeline._validate_reference_url) as validate:
                    result = fetch(expected_urls[0])

                self.assertEqual(expected_urls, [call.args[0] for call in validate.call_args_list])
                self.assertEqual(expected_urls, [call.args[0] for call in get.call_args_list])
                self.assertEqual(3, dns.call_count)
                self.assertTrue(all(call.kwargs["allow_redirects"] is False for call in get.call_args_list))
                if fetch is self.timeline._read_reference_url:
                    self.assertIn("final body", result)
                else:
                    status, text, metadata = result
                    self.assertEqual(200, status)
                    self.assertEqual("final body", text)
                    self.assertEqual(expected_urls[-1], metadata["final_url"])


if __name__ == "__main__":
    unittest.main()
