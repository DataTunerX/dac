import { DataSourceDetailView } from "@/components/data-source-detail-view";

export default async function Page(props: {
  params: Promise<{ namespace: string; name: string }>;
}) {
  await props.params;
  return <DataSourceDetailView />;
}
