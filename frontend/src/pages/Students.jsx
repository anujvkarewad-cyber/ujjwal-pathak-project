import StudentTable from '@/components/students/StudentTable';
import BatchDriftCard from '@/components/students/BatchDriftCard';
import PasswordCoverageCard from '@/components/students/PasswordCoverageCard';

export default function Students() {
  return (
    <div className="space-y-4" data-testid="students-page">
      <BatchDriftCard />
      <PasswordCoverageCard />
      <StudentTable />
    </div>
  );
}
