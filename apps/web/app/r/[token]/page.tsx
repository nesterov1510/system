import type { Metadata } from "next";
import PublicRepairView from "./PublicRepairView";

export const metadata: Metadata = {
  title: "Статус ремонта",
  robots: { index: false, follow: false },
};

export default function PublicRepairPage({
  params,
}: {
  params: { token: string };
}) {
  return <PublicRepairView token={params.token} />;
}
