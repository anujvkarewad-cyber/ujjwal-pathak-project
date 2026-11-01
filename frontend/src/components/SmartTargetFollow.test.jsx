import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import SmartTargetFollow from './SmartTargetFollow';
import { apiCall } from '@/api/backendClient';
jest.mock('@/api/backendClient', () => ({ apiCall: jest.fn() }));
const plan = { id:'local-plan', status:'active', includedBackupDays:1, revisionBudgetMinutes:30 };
const progress = { startDate:'2026-10-28',currentDay:2,totalDays:7,completedTasks:2,totalTasks:7,completedDays:1,progressPercent:14.3,overdueDays:1,backupDaysUsed:1,includedBackupDays:1,backupDaysRemaining:0,approvedExtensionDays:0,extensionDaysRemaining:0,extensionDaysNeeded:1,deadline:'2026-11-04',projectedFinishDate:'2026-11-05',days:[],extensions:[{id:'local-request',requestedDays:2,status:'pending',reason:'Local test reason'}] };
const response = { today:'2026-10-30',started:1,notStarted:1,fallingBehind:1,pendingRequests:1,students:[{studentId:'LOCAL_A',studentName:'Local fixture',inAudience:true,progress,chapters:[{revisionKey:'local-chapter',concept:'Local chapter',subject:'Taxation',strength:'weak',accuracy:0,questionAccuracy:0,questionCorrectTotal:0,questionAttemptedTotal:10,dueOn:'2026-10-29',lastAssessmentSource:'student-reported-question-score'}],dueRevisions:[{}]}] };

global.IS_REACT_ACT_ENVIRONMENT = true;
let host, root;
beforeEach(() => { apiCall.mockReset(); host=document.createElement('div'); document.body.appendChild(host); root=createRoot(host); });
afterEach(async () => { await act(async()=>root.unmount()); host.remove(); });
const button = text => [...host.querySelectorAll('button')].find(b=>b.textContent === text);
async function load() { await act(async()=>root.render(<SmartTargetFollow plan={plan}/>)); await act(async()=>button('Open student Target Follow').click()); }
async function change(label,value) { const input=host.querySelector(`[aria-label="${label}"]`); await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));}); }
test('loads persisted follow-up and distinguishes zero from unassessed',async()=>{
 apiCall.mockResolvedValue(response);await load();expect(host.textContent).toContain('1 started · 1 not started');expect(host.textContent).toContain('question accuracy 0%');expect(host.textContent).toContain('Student-reported question score');expect(apiCall).toHaveBeenCalledWith('/api/smart-targets/mentor/local-plan');
});
test('approves configurable extra days and refreshes backend state',async()=>{
 apiCall.mockResolvedValue(response);await load();await change('Grant days LOCAL_A','3');await act(async()=>button('Approve').click());expect(apiCall).toHaveBeenCalledWith('/api/smart-targets/mentor/local-plan/extension',{method:'POST',body:{studentId:'LOCAL_A',requestId:'local-request',decision:'approved',days:3,note:''}});expect(apiCall).toHaveBeenCalledTimes(3);
});
test('rejects even if grant-days input was cleared',async()=>{
 apiCall.mockResolvedValue(response);await load();await change('Grant days LOCAL_A','');await act(async()=>button('Reject').click());expect(apiCall).toHaveBeenCalledWith('/api/smart-targets/mentor/local-plan/extension',expect.objectContaining({body:expect.objectContaining({decision:'rejected',days:1})}));
});
test('read failure never fabricates progress',async()=>{
 apiCall.mockRejectedValue(new Error('Server unavailable'));await load();expect(host.querySelector('[role="alert"]').textContent).toContain('Server unavailable');expect(host.textContent).not.toContain('1 started');
});
