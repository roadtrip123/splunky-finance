# Disclaimer

**This is a demonstration project. Do not run it in production.**

## Not an official product

Splunky Finance is an independent demonstration built to show how Galileo evaluation and Agent
Control behave in a realistic agent application. It is **not a Cisco product, not a Splunk product,
and not a Galileo product.** It is not affiliated with, endorsed by, sponsored by, or supported by
Cisco, Splunk, Galileo, or any other company whose products or trademarks it references. Those names
appear only to identify the third-party services this demonstration integrates with.

Nothing here carries any form of product support. Do not raise support cases against any vendor for
its behaviour.

## Not a bank

"Splunky Finance" is a fictional Australian bank. Every account, customer, balance, transaction,
policy document and interest rate is synthetic and generated from a seed. **No banking action
executes anywhere.** Transfers move numbers inside a local JSON file. Nothing touches a payment
network, a real institution, or any real person's money or data.

It is not financial advice, and the policy documents it cites are invented.

## Not production software

The deployment is deliberately built for a demonstration and a workshop, and it makes trade-offs that
would be defects in a production system:

- **Shared, fixed, published passwords.** Every participant signs in with the same credentials, which
  a presenter reads aloud. They are in the repository on purpose.
- **Plain HTTP and self-signed TLS are both supported paths.** On the private-network path, API keys
  participants paste into the portal cross the network in cleartext.
- **Credentials are stored to make the demonstration work**, not to a standard suitable for real
  secrets. Participants paste their own third-party API keys into a portal that keeps them in a local
  volume.
- **Data is wiped and regenerated on demand**, and faults are injected into model output on purpose,
  because showing an evaluator catching a bad answer is the point.
- **No authorisation model, no audit trail, no tenancy, no backups.** There is one synthetic customer
  per stack and a presenter view with no separation beyond a second password.

Use it to learn, to demonstrate, and to run workshops. Do not put it in front of real customers, real
money, real personal data, or a real network you care about.

## No warranty

Provided as-is, without warranty of any kind, express or implied. The authors accept no liability for
any loss or damage arising from its use.
