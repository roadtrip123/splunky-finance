# Extra trusted certificate authorities for the image build

Empty by default, and empty is correct on a normal network.

Put PEM files here when the build runs behind a TLS-intercepting proxy — a corporate network that
substitutes its own certificate for every HTTPS connection. The host usually trusts that CA already,
which is why `git` and `apt` work, but the build container has its own trust store and does not, so
`uv sync` fails with:

```
invalid peer certificate: certificate not valid for name "files.pythonhosted.org";
certificate is only valid for DnsName("*.example.internal")
```

On the build host:

```bash
cp /etc/ssl/certs/ca-certificates.crt backend/ca/host-bundle.crt
```

That copies the host's whole trust store, the proxy's CA included, and is the quickest fix. To add
only the proxy's own certificate instead:

```bash
openssl s_client -connect files.pythonhosted.org:443 -showcerts </dev/null 2>/dev/null \
  | awk '/BEGIN CERT/,/END CERT/' > backend/ca/proxy.crt
```

Files here are gitignored. They are public certificates, not secrets, but they identify an internal
network and do not belong in a shared repository.
