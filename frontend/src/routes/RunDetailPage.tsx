import { useParams } from 'react-router-dom';

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <div data-testid="page-run-detail">Run detail (M2-8 placeholder) — id: {id}</div>;
}
