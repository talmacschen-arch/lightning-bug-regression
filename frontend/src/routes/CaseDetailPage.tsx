import { useParams } from 'react-router-dom';

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <div data-testid="page-case-detail">Case detail (M2-6 placeholder) — id: {id}</div>;
}
