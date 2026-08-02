// Dummy student data. Structure designed to be easily replaced by Google Apps Script API responses later.
const AVATARS = [
  'https://images.unsplash.com/photo-1514960919797-5ff58c52e5ba?crop=entropy&cs=srgb&fm=jpg&q=85&w=200',
  'https://images.unsplash.com/photo-1548810020-ea2f1da35cff?crop=entropy&cs=srgb&fm=jpg&q=85&w=200',
  'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?crop=entropy&cs=srgb&fm=jpg&q=85&w=200',
  'https://images.unsplash.com/photo-1544168190-79c17527004f?crop=entropy&cs=srgb&fm=jpg&q=85&w=200',
  'https://images.pexels.com/photos/7983621/pexels-photo-7983621.jpeg?auto=compress&cs=tinysrgb&w=200',
  'https://images.unsplash.com/photo-1531123897727-8f129e1688ce?crop=entropy&cs=srgb&fm=jpg&q=85&w=200',
  'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?crop=entropy&cs=srgb&fm=jpg&q=85&w=200',
  'https://images.unsplash.com/photo-1580489944761-15a19d654956?crop=entropy&cs=srgb&fm=jpg&q=85&w=200',
];

const FIRST_NAMES = ['Aarav', 'Vivaan', 'Aditya', 'Vihaan', 'Arjun', 'Sai', 'Reyansh', 'Krishna', 'Ishaan', 'Rudra', 'Aanya', 'Diya', 'Isha', 'Kavya', 'Myra', 'Ananya', 'Riya', 'Priya', 'Saanvi', 'Meera', 'Rohan', 'Kabir', 'Neel', 'Yash', 'Advik', 'Aarohi', 'Navya', 'Ira', 'Pari', 'Zara'];
const LAST_NAMES = ['Sharma', 'Verma', 'Patel', 'Gupta', 'Iyer', 'Reddy', 'Nair', 'Kumar', 'Singh', 'Joshi', 'Mehta', 'Kapoor', 'Malhotra', 'Bansal', 'Agarwal'];
const BATCHES = ['Super 30', 'Super 11', 'Last 15 Days', 'Last 40 Days'];
const GROUPS = ['Group 1', 'Group 2', 'Both Groups'];
const LEVELS = ['CA Foundation', 'CA Intermediate', 'CA Final'];
const STATUSES = ['Active', 'Inactive', 'At Risk'];

function seededRandom(seed) {
  let x = Math.sin(seed) * 10000;
  return x - Math.floor(x);
}

function generateStudents(count = 50) {
  const students = [];
  for (let i = 0; i < count; i++) {
    const r = (n) => seededRandom(i * 100 + n);
    const first = FIRST_NAMES[Math.floor(r(1) * FIRST_NAMES.length)];
    const last = LAST_NAMES[Math.floor(r(2) * LAST_NAMES.length)];
    const attendance = Math.floor(60 + r(3) * 40);
    const studyHours = +(2 + r(4) * 8).toFixed(1);
    const submissionRate = Math.floor(50 + r(6) * 50);
    const risk = attendance < 70 ? 'At Risk' : (attendance < 80 ? 'Watch' : 'Healthy');
    const status = risk === 'At Risk' ? 'At Risk' : (r(7) > 0.15 ? 'Active' : 'Inactive');
    const weekly = Array.from({ length: 7 }, (_, d) => ({
      day: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d],
      hours: +(1 + seededRandom(i * 10 + d) * 9).toFixed(1),
    }));
    const monthly = Array.from({ length: 4 }, (_, w) => ({
      week: `Week ${w + 1}`,
      attendance: Math.floor(60 + seededRandom(i * 30 + w) * 40),
      hours: +(15 + seededRandom(i * 50 + w) * 40).toFixed(1),
    }));
    students.push({
      id: `STU-${String(1001 + i).padStart(4, '0')}`,
      name: `${first} ${last}`,
      email: `${first.toLowerCase()}.${last.toLowerCase()}@upmentor.in`,
      phone: `+91 9${Math.floor(100000000 + r(8) * 899999999)}`,
      avatar: AVATARS[i % AVATARS.length],
      batch: BATCHES[Math.floor(r(9) * BATCHES.length)],
      attempt: 'Sept 2026',
      group: GROUPS[Math.floor(r(10) * GROUPS.length)],
      level: LEVELS[Math.floor(r(11) * LEVELS.length)],
      status,
      risk,
      attendance,
      studyHours,
      submissionRate,
      joinedOn: `2025-${String(Math.floor(1 + r(12) * 9)).padStart(2, '0')}-${String(Math.floor(1 + r(13) * 27)).padStart(2, '0')}`,
      city: ['Mumbai', 'Delhi', 'Bengaluru', 'Chennai', 'Pune', 'Kolkata', 'Hyderabad', 'Ahmedabad'][Math.floor(r(14) * 8)],
      mentorNotes: [
        { date: '2026-01-12', note: 'Improved MCQ accuracy this week. Encourage regular revision.' },
        { date: '2026-01-05', note: 'Missed two daily submissions. Follow up needed.' },
      ],
      weekly,
      monthly,
      tracker: Array.from({ length: 14 }, (_, d) => ({
        date: `2026-02-${String(d + 1).padStart(2, '0')}`,
        submitted: seededRandom(i * 60 + d) > 0.2,
        hours: +(1 + seededRandom(i * 70 + d) * 8).toFixed(1),
      })),
    });
  }
  return students;
}

export const students = generateStudents(50);
export const batchOptions = ['All Batches', ...BATCHES];
export const attemptOptions = ['All Attempts', 'Sept 2026'];
export const groupOptions = ['All Groups', ...GROUPS];
export const statusOptions = ['All Status', ...STATUSES];
