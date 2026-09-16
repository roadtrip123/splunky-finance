import AccountHistory from "@/components/AccountHistory";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <AccountHistory id={id} />;
}
