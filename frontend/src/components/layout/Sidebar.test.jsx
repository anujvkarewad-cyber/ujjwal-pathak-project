import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
// CRA's Jest resolver cannot resolve this installed router version's exports.
// This test checks the navigation inventory, not router behavior.
jest.mock('react-router-dom', () => ({ NavLink: ({ to, children, onClick, ...props }) => require('react').createElement('a', { href: to, onClick, 'data-testid': props['data-testid'] }, children) }), { virtual: true });
import Sidebar from './Sidebar';
global.IS_REACT_ACT_ENVIRONMENT = true;
test('main navigation has no duplicate cohort tools and global administration stays collapsed', async () => {
  const host = document.createElement('div'); document.body.appendChild(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<Sidebar open={false} onClose={() => {}} />));
    const groups = host.querySelectorAll('nav details');
    expect([...groups[0].querySelectorAll('a')].map(a => a.getAttribute('href'))).toEqual(['/', '/batches', '/sheet-sources', '/settings']);
    for (const name of ['students', 'daily-tracker', 'tests', 'notes', 'messages', 'announcements', 'leaderboard', 'password-reset']) expect(host.querySelector(`[data-testid="nav-${name}"]`)).toBeNull();
    expect(groups[1].open).toBe(false); expect(groups[2].open).toBe(false);
    const paths = [...host.querySelectorAll('nav a')].map(a => a.getAttribute('href'));
    expect(new Set(paths).size).toBe(paths.length);
  } finally { await act(async () => root.unmount()); host.remove(); }
});
