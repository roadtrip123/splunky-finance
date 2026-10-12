"""The boot-time removal of the port 443 redirect.

The redirect is saved in the image's /etc/iptables/rules.v4 and restored by netfilter-persistent on
every boot, so a box can be healthy in every internal respect and unreachable from a browser. These
tests cover the two things that made that fault survive several attempts to fix it: the rule is
spelled more than one way, and it is restored after anything that removes it too early.
"""

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
