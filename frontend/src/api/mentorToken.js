// Mentor session token transport for the Apps Script calls.
//
// The Apps Script used to answer any caller, which exposed the student roster —
// student emails, phone numbers, private mentor notes and proof links — to anyone
// who read the public bundle. The script now verifies this token before serving
// anything sensitive.
//
// Kept dependency-free so it can be unit tested without pulling in the app graph.
export function withMentorToken(url, token) {
  const value = String(token || '').trim();
  if (!value) return url;
  url.searchParams.set('token', value);
  return url;
}
