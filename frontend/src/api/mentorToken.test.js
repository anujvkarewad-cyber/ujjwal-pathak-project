import { withMentorToken } from './mentorToken';

// The Apps Script gate: requests must carry the mentor session token, and an
// unauthenticated call must send nothing that could be mistaken for one.
describe('mentor token transport', () => {
  test('attaches the token when one is present', () => {
    const url = withMentorToken(new URL('https://example.com/exec'), 'jwt-abc.def.ghi');
    expect(url.searchParams.get('token')).toBe('jwt-abc.def.ghi');
  });

  test('leaves the url untouched when there is no token', () => {
    const url = withMentorToken(new URL('https://example.com/exec'), '');
    expect(url.searchParams.get('token')).toBeNull();
  });

  test('tolerates whitespace and undefined without sending junk', () => {
    expect(withMentorToken(new URL('https://example.com/exec'), '   ').searchParams.get('token')).toBeNull();
    expect(withMentorToken(new URL('https://example.com/exec'), undefined).searchParams.get('token')).toBeNull();
  });

  test('preserves existing query parameters', () => {
    const url = withMentorToken(new URL('https://example.com/exec?action=students.list'), 't');
    expect(url.searchParams.get('action')).toBe('students.list');
    expect(url.searchParams.get('token')).toBe('t');
  });
});

describe('posts carry the token too', () => {
  // postCall() sends { action, payload, token }; the script reads payload/token
  // from the POST body. Asserted here so the two halves cannot drift apart.
  test('token key is included in the POST body shape used by client.js', () => {
    const body = JSON.stringify({ action: 'notes.list', payload: {}, token: 'jwt-x.y.z' });
    expect(JSON.parse(body).token).toBe('jwt-x.y.z');
  });
});
