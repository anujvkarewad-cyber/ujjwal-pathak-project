import StudentTable from '@/components/students/StudentTable';

export default function Students() {
  return (
    <div className="space-y-4" data-testid="students-page">
      <StudentTable />
    </div>
  );
}
