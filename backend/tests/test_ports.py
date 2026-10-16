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
    proves nothing about whether the site is matched on it."""
    assert '--connect-to "$HOST:$PORT:127.0.0.1:$EXTRA"' in installer()


def test_the_unit_is_documented_as_insurance_rather_than_the_mechanism():
    """So that a later reader does not conclude the portal depends on this unit running."""
    assert "Insurance, not the mechanism" in unit("splunky-finance-ports.service")
