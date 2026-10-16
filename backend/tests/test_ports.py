"""The port 443 redirect: serving around it, and removing it.

The redirect is saved in the image's /etc/iptables/rules.v4 and restored by netfilter-persistent on
every boot, so a box can be healthy in every internal respect and unreachable from a browser. These
tests cover the two things that made that fault survive several attempts to fix it: the rule is
spelled more than one way, and it is restored after anything that removes it too early.

They also cover the stronger defence that replaced refusing to install at all: the proxy serves the
rule's destination port as well as the public one, so arriving traffic is answered whether the rule
is present or not, with nothing to run at boot. That matters where the rule is restored by something
outside the box while it is running, which no deletion strategy can survive.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

# Imported after the path above is set, which is why these are not at the top.
import fix_ports
import install_service
import serve_any_host
import serve_redirect_port

SAVED = "-A PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 8443"


@pytest.mark.parametrize(
    "rule",
    [
        SAVED,
        # Added by hand, without the implicit match module spelled out.
        "-A PREROUTING -p tcp --dport 443 -j REDIRECT --to-ports 8443",
        # The destination port has varied between boxes; it is the hijack of 443 that matters.
        "-A PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 9443",
        "-A PREROUTING -i ens5 -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 8443",
    ],
)
def test_matches_every_spelling_of_the_hijack(rule):
    assert fix_ports.REDIRECT_443.search(rule)


@pytest.mark.parametrize(
    "rule",
    [
        # Docker's own rules live in the same table and must survive.
        "-A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE",
        "-A PREROUTING -m addrtype --dst-type LOCAL -j DOCKER",
        # A redirect of a different port is somebody's deliberate choice, not this fault.
        "-A PREROUTING -p tcp -m tcp --dport 80 -j REDIRECT --to-ports 8080",
        # A forward of 443 to another host is a different mechanism and not what breaks the box.
        "-A PREROUTING -p tcp -m tcp --dport 443 -j DNAT --to-destination 10.0.0.5:8443",
        # The RETURN rules that keep container egress off the redirect.
        "-A PREROUTING -i docker0 -j RETURN",
    ],
)
def test_leaves_unrelated_rules_alone(rule):
    assert not fix_ports.REDIRECT_443.search(rule)


def test_counts_duplicates_because_the_first_box_had_two():
    listing = f"-A PREROUTING -i docker0 -j RETURN\n{SAVED}\n{SAVED}"
    assert len(fix_ports.offending(listing)) == 2


class _ok:
    returncode = 0
    stdout = ""
    stderr = ""


def test_delete_inverts_the_listed_rule(monkeypatch):
    """`iptables -S` prints what to append; removing it means the same spec with -D."""
    calls = []
    monkeypatch.setattr(fix_ports, "iptables", lambda *a, **k: calls.append(a) or _ok())
    fix_ports.delete(SAVED)
    assert calls == [
        ("-D", "PREROUTING", "-p", "tcp", "-m", "tcp", "--dport", "443",
         "-j", "REDIRECT", "--to-ports", "8443")
    ]


def test_delete_refuses_anything_that_is_not_an_append():
    with pytest.raises(ValueError):
        fix_ports.delete("-P PREROUTING ACCEPT")


def unit(name):
    return (ROOT / "scripts" / name).read_text()


def test_the_unit_runs_after_the_rules_are_restored():
    """Ordering is the fault's whole character: restored at boot, so an early fix is undone."""
    text = unit("splunky-finance-ports.service")
    assert "After=netfilter-persistent.service" in text
    assert "Before=splunky-finance.service" in text


def test_the_unit_stays_root():
    """install_service.py rewrites User= in every unit; this one must not have the line at all,
    because editing the nat table as the repository owner fails."""
    text = unit("splunky-finance-ports.service")
    assert not any(line.startswith("User=") for line in text.splitlines())


def test_the_unit_removes_the_saved_copy_too():
    assert "fix_ports.py --persist" in unit("splunky-finance-ports.service")


def test_the_installer_installs_and_enables_it():
    assert "splunky-finance-ports.service" in install_service.UNITS
    source = (ROOT / "scripts" / "install_service.py").read_text()
    assert '"enable", "--now", "splunky-finance-ports.service"' in source


def installer():
    return (ROOT / "scripts" / "install.sh").read_text()


def destination_expression():
    """The sed expression install.sh reads the redirect's destination port with, as it ships.

    Pulled out of the script and run for real rather than copied here: a copy would keep passing
    after the original was edited, and this expression is the whole of the detection.
    """
    for line in installer().splitlines():
        if "--to-ports" in line and line.strip().startswith("| sed -n"):
            return line[line.index('"') + 1 : line.rindex('"')].replace("$PORT", "443")
    raise AssertionError("install.sh no longer reads the destination port with sed")


def found_destinations(*rules):
    result = subprocess.run(
        ["sed", "-n", destination_expression()],
        input="\n".join(rules) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.split())


def test_the_installer_reads_the_destination_from_every_spelling():
    """Same spellings as above. The destination is what decides which port to serve."""
    assert found_destinations(SAVED) == {"8443"}
    assert found_destinations("-A PREROUTING -p tcp --dport 443 -j REDIRECT --to-ports 8443") == {
        "8443"
    }
    assert found_destinations(
        "-A PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 9443"
    ) == {"9443"}
    assert found_destinations(
        "-A PREROUTING -i ens5 -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 8443"
    ) == {"8443"}


def test_the_installer_ignores_rules_that_are_not_this_fault():
    assert not found_destinations(
        # A redirect of a different port is somebody's deliberate choice.
        "-A PREROUTING -p tcp -m tcp --dport 80 -j REDIRECT --to-ports 8080",
        # A longer port number that merely starts with 443.
        "-A PREROUTING -p tcp -m tcp --dport 4433 -j REDIRECT --to-ports 9999",
        # A forward to another host is a different mechanism.
        "-A PREROUTING -p tcp -m tcp --dport 443 -j DNAT --to-destination 10.0.0.5:8443",
        "-A PREROUTING -i docker0 -j RETURN",
    )


def test_a_redirect_no_longer_stops_the_install():
    """It used to die here, which left a lab image with no way to install at all."""
    source = installer()
    assert "would never receive traffic" not in source
    assert "ALSO_PORTS" in source


def test_the_second_port_defaults_to_8443_behind_the_standard_public_port():
    assert 'if [ -z "$ALSO_PORTS" ] && [ "$PORT" = "443" ]; then ALSO_PORTS="8443"; fi' in installer()


def test_the_site_block_carries_every_address_it_answers_on():
    """One site block, comma-separated. Caddy strips the port when matching the Host header, so a
    browser asking for 443 is served by the listener the redirect lands on."""
    source = installer()
    assert 'SITE="$SITE, $HOST:$EXTRA"' in source
    # The scheme moved into SITE, so the plain-HTTP branch cannot hardcode one address any more.
    assert "http://%s {" not in source
    assert 'if [ "$MODE" = "lan-http" ]; then SITE="http://$SITE"; fi' in source


def test_an_occupied_second_port_is_skipped_rather_than_fatal():
    """The public port still works without it, and taking the install down over a secondary
    address would be the worse trade."""
    source = installer()
    block = source[source.index('for CANDIDATE in $ALSO_PORTS') : source.index('ALSO_PORTS="$KEPT"')]
    assert "continue" in block
    assert "die" not in block


def test_the_installer_verifies_the_redirected_path_and_not_only_the_direct_one():
    """With the Host header a browser sends, into the port the redirect lands on. Binding a port
    proves nothing about whether the site is matched on it. The host is the probe name, which for
    a wildcard deployment is a name the proxy was never told about."""
    assert '--connect-to "$PROBE_HOST:$PORT:127.0.0.1:$EXTRA"' in installer()


def test_the_unit_is_documented_as_insurance_rather_than_the_mechanism():
    """So that a later reader does not conclude the portal depends on this unit running."""
    assert "Insurance, not the mechanism" in unit("splunky-finance-ports.service")


# The Caddyfile shapes this project generates. Editing the wrong one is the risk: a workshop box
# serves a port per participant and a LAN box serves plain HTTP, and neither is this fault.
THEIRS = """splunkyfinance.splunk.show {
	tls /etc/caddy/tls.crt /etc/caddy/tls.key
	reverse_proxy 127.0.0.1:3000
}
"""
SELF_SIGNED = """{
	auto_https disable_redirects
	default_sni 203.0.113.10
	skip_install_trust
}
203.0.113.10 {
	tls internal
	reverse_proxy 127.0.0.1:3000
}
"""
WORKSHOP = """{
	auto_https disable_redirects
}
203.0.113.10:3101 {
	reverse_proxy 127.0.0.1:4101
}
203.0.113.10:3102 {
	reverse_proxy 127.0.0.1:4102
}
"""
LAN_HTTP = """{
	auto_https off
}
http://192.168.1.50 {
	reverse_proxy 127.0.0.1:3000
}
"""


def serve(text, public_port=443, destination=8443):
    return serve_redirect_port.rewrite(text, public_port, destination)


def test_the_destination_is_read_from_the_rule():
    assert serve_redirect_port.destinations(SAVED, 443) == [8443]
    assert serve_redirect_port.destinations(
        "-A PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 9443", 443
    ) == [9443]


def test_unrelated_rules_name_no_destination():
    for rule in (
        "-A PREROUTING -p tcp -m tcp --dport 80 -j REDIRECT --to-ports 8080",
        "-A PREROUTING -p tcp -m tcp --dport 443 -j DNAT --to-destination 10.0.0.5:8443",
        "-A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE",
    ):
        assert serve_redirect_port.destinations(rule, 443) == []


def test_a_hostname_site_gains_the_second_address():
    """The shape on the box this was written for: a hostname, a supplied certificate, no port."""
    updated, changed = serve(THEIRS)
    assert changed == ["splunkyfinance.splunk.show"]
    assert updated.splitlines()[0] == (
        "splunkyfinance.splunk.show:443, splunkyfinance.splunk.show:8443 {"
    )
    # Everything else is left exactly as it was, tabs and all.
    assert updated.splitlines()[1:] == THEIRS.splitlines()[1:]


def test_an_ip_site_keeps_its_global_options():
    updated, changed = serve(SELF_SIGNED)
    assert changed == ["203.0.113.10"]
    assert "203.0.113.10:443, 203.0.113.10:8443 {" in updated
    assert "default_sni 203.0.113.10" in updated
    # The global options block opens with a bare brace and must never be treated as an address.
    assert updated.startswith("{\n")


def test_a_port_per_participant_is_left_alone():
    """Fifty stacks on 3101 upward have nothing to do with a redirect of 443."""
    updated, changed = serve(WORKSHOP)
    assert changed == []
    assert updated == WORKSHOP


def test_plain_http_is_left_alone():
    updated, changed = serve(LAN_HTTP)
    assert changed == []
    assert updated == LAN_HTTP


def test_running_it_twice_changes_nothing_the_second_time():
    once, changed = serve(THEIRS)
    assert changed
    twice, changed_again = serve(once)
    assert changed_again == []
    assert twice == once


def test_an_unrecognised_address_is_left_alone_rather_than_guessed_at():
    odd = "*.demo.example.com, :443 {\n\treverse_proxy 127.0.0.1:3000\n}\n"
    updated, changed = serve(odd)
    assert changed == []
    assert updated == odd


# The lab platform names each instance when it boots, so the proxy cannot be told the name in
# advance. Serving by port alone, under a wildcard certificate, is what makes one image work
# everywhere with nothing to run at boot.
NAMED_BOTH_PORTS = """i-09c3ad076563d756c.splunk.show:443, i-09c3ad076563d756c.splunk.show:8443 {
\ttls /etc/caddy/tls.crt /etc/caddy/tls.key
\treverse_proxy 127.0.0.1:3000
}
"""


def any_host(text, public_port=443, destination=8443):
    return serve_any_host.rewrite(text, public_port, destination)


def test_the_name_is_dropped_so_every_instance_is_served():
    updated, changed = any_host(NAMED_BOTH_PORTS)
    assert changed == ["i-09c3ad076563d756c.splunk.show"]
    assert updated.splitlines()[0] == ":443, :8443 {"
    assert updated.splitlines()[1:] == NAMED_BOTH_PORTS.splitlines()[1:]


def test_a_named_site_on_one_port_gains_the_second_and_loses_the_name():
    updated, changed = any_host(THEIRS)
    assert changed == ["splunkyfinance.splunk.show"]
    assert updated.splitlines()[0] == ":443, :8443 {"


def test_the_host_is_reported_once_not_once_per_address():
    """Both addresses carry the same name, and saying it twice reads like two sites."""
    _, changed = any_host(NAMED_BOTH_PORTS)
    assert len(changed) == 1


def test_serving_by_port_leaves_a_port_per_participant_alone():
    assert any_host(WORKSHOP) == (WORKSHOP, [])


def test_serving_by_port_leaves_plain_http_alone():
    """A wildcard origin requires HTTPS, so this box cannot use one."""
    assert any_host(LAN_HTTP) == (LAN_HTTP, [])


def test_serving_by_port_is_idempotent():
    once, changed = any_host(NAMED_BOTH_PORTS)
    assert changed
    assert any_host(once) == (once, [])


def test_the_installer_serves_by_port_for_a_wildcard_host():
    """`--host '*.example.com'` writes a site block with no name in it at all."""
    source = installer()
    assert 'is_wildcard() { case "$1" in "*."*) return 0 ;; *) return 1 ;; esac; }' in source
    assert 'SITE=":$PORT"' in source
    assert 'if is_wildcard "$HOST"; then SITE="$SITE, :$EXTRA"' in source


def test_the_installer_refuses_to_issue_a_wildcard_certificate_itself():
    """ACME needs a DNS challenge for a wildcard, which this script does not do."""
    source = installer()
    assert "--acme cannot issue for $HOST here" in source


def test_the_installer_verifies_a_wildcard_with_a_name_it_was_never_told():
    """Nothing can connect to "*.example.com", and a name under it is the better test anyway."""
    source = installer()
    assert 'PROBE_HOST="probe.${HOST#\\*.}"' in source
    assert '--connect-to "$PROBE_HOST:$PORT:127.0.0.1:$PORT"' in source
    assert '--connect-to "$PROBE_HOST:$PORT:127.0.0.1:$EXTRA"' in source


def test_the_any_host_script_refuses_an_old_checkout():
    """Setting a wildcard origin against a backend that compares strings would be accepted at
    startup and then refuse every request, with a 403 on login and no obvious cause."""
    source = (ROOT / "scripts" / "serve_any_host.py").read_text()
    assert "def backend_understands_wildcards" in source
    assert "if not backend_understands_wildcards():" in source
    assert serve_any_host.backend_understands_wildcards()


def snapshot_script():
    return (ROOT / "scripts" / "reset_for_snapshot.sh").read_text()


def test_the_snapshot_reset_clears_credentials_from_env_rather_than_warning():
    """Destroying the volume does not touch .env, which is deliberately kept for the address and
    the demo passwords. A key left there is baked into every clone, and warning about it only
    works if somebody reads the warning."""
    source = snapshot_script()
    for field in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GALILEO_API_KEY",
        "SPLUNK_AO_API_KEY",
        "SPLUNK_AO_O11Y_TOKEN",
        "SPLUNK_AO_O11Y_API_TOKEN",
    ):
        assert field in source, field
    assert 'sed -i "s|^$1=.*|$1=|"' in source
    assert "for FIELD in $SECRETS; do blank" in source


def test_the_snapshot_reset_clears_the_project_name_too():
    """Not a credential, but the lab has each participant create their own project. A field
    arriving pre-filled with somebody else's name either fails with "project not found" or, worse,
    succeeds and sends their traces somewhere that is not theirs."""
    source = snapshot_script()
    assert "GALILEO_PROJECT" in source
    assert "for FIELD in $NAMES; do blank" in source


def test_the_snapshot_reset_leaves_the_stream_at_the_name_the_lab_uses():
    """my-bank-agent is the application default and what lab step 10 tells participants to type,
    so resetting it saves a step rather than setting a trap."""
    source = snapshot_script()
    assert 'STREAM_DEFAULT="my-bank-agent"' in source
    assert "GALILEO_LOG_STREAM=$STREAM_DEFAULT" in source


def test_the_snapshot_reset_refuses_to_pass_with_values_still_set():
    """The old version warned and carried on, which is how a box reaches an image with a key in
    it. These were just cleared, so anything left means an edit failed silently."""
    source = snapshot_script()
    assert "participant-specific values remain in .env; do not snapshot this box." in source
    assert "LEFTOVER" in source


def test_the_snapshot_reset_restarts_so_the_running_stack_matches_env():
    """The stack is already up by that point, holding the values just cleared."""
    source = snapshot_script()
    cleared = source.index("Clearing participant-specific values from .env")
    carries = source.index("What this image will carry")
    assert "Restarting so the cleared values are what the application is running" in source
    assert cleared < source.index("Restarting so the cleared values") < carries


def test_tenant_urls_are_kept_unless_asked_for():
    """They are not credentials, and an image that carries them saves the instructor reading them
    out. --blank-urls is there for anyone who disagrees."""
    source = snapshot_script()
    assert "--blank-urls) BLANK_URLS=1" in source
    assert 'if [ "$BLANK_URLS" -eq 1 ]; then' in source
    assert "kept       $FIELD=$VALUE" in source
