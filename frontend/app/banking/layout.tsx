import { requireCustomer } from "@/lib/server";
import Shell from "@/components/Shell";
export default async function BankingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requireCustomer();
  return <Shell>{children}</Shell>;
}
