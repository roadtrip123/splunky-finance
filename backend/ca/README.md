# Extra trusted certificate authorities for the image build

Empty by default, and empty is correct on a normal network.

Put PEM files here when the build runs behind a genuine TLS-intercepting proxy — a network that
substitutes its own certificate for every HTTPS connection. The host usually trusts that CA already,
which is why `git` and `apt` work, but the build container has its own trust store and does not, so
`uv sync` fails with an **issuer** error:

```
invalid peer certificate: UnknownIssuer
```

This directory does not fix a **name** error:

```
certificate not valid for name "files.pythonhosted.org";
certificate is only valid for DnsName("*.lab.example")
```

That is a different problem — the connection is being redirected to another server, not intercepted,
and no amount of trusted CAs makes the name match. See `docs/workshop.md`, "When the image build
cannot reach PyPI or npm", which covers it with `BUILD_NETWORK=host`.

For a real issuer error, check whether the host trusts the proxy:

```bash
curl -sI https://files.pythonhosted.org/ | head -1
```

**If that succeeds**, the host's store has the CA and copying it is the quickest fix:

```bash
cp /etc/ssl/certs/ca-certificates.crt backend/ca/host-bundle.crt
```

**If it fails with a certificate error**, take the certificate the proxy actually presents, which
works either way because `s_client` does not verify before printing:

```bash
openssl s_client -connect files.pythonhosted.org:443 -showcerts </dev/null 2>/dev/null \
  | awk '/BEGIN CERT/,/END CERT/' > backend/ca/proxy.crt
```

Files here are gitignored. They are public certificates, not secrets, but they identify an internal
network and do not belong in a shared repository.
