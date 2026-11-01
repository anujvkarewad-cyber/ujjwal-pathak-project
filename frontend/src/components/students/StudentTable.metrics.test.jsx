import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import StudentTable from './StudentTable';
import { useStudents } from '@/api/hooks';
jest.mock('@/api/hooks', () => ({ useStudents: jest.fn(() => ({ isLoading: false })) }));
jest.mock('react-router-dom', () => ({ Link: ({ to, children, ...props }) => require('react').createElement('a', {href:to,...props}, children) }), { virtual:true });
global.IS_REACT_ACT_ENVIRONMENT=true;
let host,root;
beforeEach(()=>{useStudents.mockReturnValue({isLoading:false});host=document.createElement('div');document.body.appendChild(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
const student={id:'UMP0001',name:'Current student',batch:'Current batch',group:'Group 1'};
test('provided roster displays joined attendance/status/risk without enabling legacy enrichment',async()=>{
 await act(async()=>root.render(<StudentTable providedStudents={[{...student,attendance:85,status:'Active',risk:'Healthy'}]} showMetricsSource />));
 expect(useStudents).toHaveBeenLastCalledWith({enabled:false});
 const row=host.querySelector('[data-testid="row-UMP0001"]');
 expect(row.textContent).toContain('85%');expect(row.textContent).toContain('Active');expect(row.textContent).toContain('Healthy');
 expect([...host.querySelectorAll('[data-testid="filter-status"] option')].map(x=>x.value)).toContain('Active');
});
test('failed metrics retain the enrollment row and never show zero attendance or an at-risk badge',async()=>{
 await act(async()=>root.render(<StudentTable providedStudents={[{...student,attendance:null,status:null,risk:null}]} showMetricsSource metricsError={new Error('Offline')} />));
 const row=host.querySelector('[data-testid="row-UMP0001"]');expect(row.textContent).toContain('Current student');expect(row.textContent).toContain('Unavailable');expect(row.textContent).toContain('Not assessed');expect(row.textContent).not.toContain('0%');expect(row.textContent).not.toContain('At Risk');expect(host.querySelector('[role="alert"]').textContent).toContain('Metrics could not load');
});
