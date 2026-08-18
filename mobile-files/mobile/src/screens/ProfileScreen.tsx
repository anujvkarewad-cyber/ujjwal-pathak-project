import { Ionicons } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import React, { useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Card, InitialsAvatar, PrimaryButton } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useData } from '../context/DataContext';
import { useNotifications } from '../context/NotificationsContext';
import { useProgressSync } from '../context/ProgressSyncContext';
import { colors, radius, spacing } from '../theme';

const InfoRow = ({ icon, label, value }: { icon: keyof typeof Ionicons.glyphMap; label: string; value?: string }) => (
  <View style={styles.infoRow}>
    <View style={styles.infoIcon}><Ionicons name={icon} size={19} color={colors.primary} /></View>
    <View style={styles.infoBody}><Text style={styles.infoLabel}>{label}</Text><Text style={styles.infoValue}>{value || '—'}</Text></View>
  </View>
);

const MenuRow = ({ icon, title, subtitle, onPress }: { icon: keyof typeof Ionicons.glyphMap; title: string; subtitle: string; onPress: () => void }) => (
  <Pressable onPress={onPress} style={({ pressed }) => [styles.menuRow, pressed && { backgroundColor: colors.primarySoft }]}>
    <View style={styles.menuIcon}><Ionicons name={icon} size={20} color={colors.primary} /></View>
    <View style={styles.menuBody}><Text style={styles.menuTitle}>{title}</Text><Text style={styles.menuSubtitle}>{subtitle}</Text></View>
    <Ionicons name="chevron-forward" size={18} color={colors.muted} />
  </Pressable>
);

export const ProfileScreen = () => {
  const navigation = useNavigation<any>();
  const { student, logout, backendMode } = useAuth();
  const { data } = useData();
  const { pushStatus, enablePush } = useNotifications();
  const { sharing: progressSharing, setSharing: setProgressSharing } = useProgressSync();
  const [progressBusy, setProgressBusy] = useState(false);
  const pushEnabled = pushStatus === 'enabled';

  const confirmSharingToggle = (on: boolean) => {
    const body = on
      ? 'Mentor Ujjwal Pathak will see chapter-level MCQ summaries (no raw answers) to guide your progress.'
      : 'Your MCQ progress will stop being shared with your mentor. Existing summaries may remain.';
    Alert.alert(on ? 'Share progress with mentor?' : 'Stop sharing progress?', body, [
      { text: 'Cancel', style: 'cancel' },
      { text: on ? 'Share' : 'Stop', onPress: () => { setProgressBusy(true); setProgressSharing(on).finally(() => setProgressBusy(false)); } },
    ]);
  };
  const pushMessage = pushEnabled ? 'Background alerts are active on this device.'
    : pushStatus === 'denied' ? 'Permission is blocked. Enable notifications from Android app settings.'
      : pushStatus === 'configuration-required' ? 'Firebase Android configuration is required in this build.'
        : pushStatus === 'requesting' ? 'Registering this device for mentorship alerts…'
          : 'Enable alerts for new material and mentor updates.';

  const confirmLogout = () => Alert.alert('Sign out?', 'You will need your Student ID and password to sign in again.', [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Sign out', style: 'destructive', onPress: () => logout() },
  ]);

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.header}><Text style={styles.eyebrow}>YOUR ACCOUNT</Text><Text style={styles.title}>Profile</Text></View>

        <Card style={styles.profileCard}>
          <InitialsAvatar name={student?.studentName || 'Student'} size={76} />
          <Text style={styles.name}>{student?.studentName}</Text>
          <Text style={styles.studentId}>{student?.studentId}</Text>
          <View style={styles.tags}>
            <View style={styles.tag}><Text style={styles.tagText}>{student?.caLevel || 'Student'}</Text></View>
            <View style={[styles.tag, styles.groupTag]}><Text style={[styles.tagText, styles.groupTagText]}>{student?.group || 'Mentorship'}</Text></View>
          </View>
          <View style={styles.profileStats}>
            <View style={styles.profileStat}><Text style={styles.profileStatValue}>{Number(data.stats.totalHours || 0).toFixed(1).replace('.0', '')}h</Text><Text style={styles.profileStatLabel}>TOTAL STUDY</Text></View>
            <View style={styles.profileDivider} />
            <View style={styles.profileStat}><Text style={styles.profileStatValue}>{data.stats.streak || 0}</Text><Text style={styles.profileStatLabel}>DAY STREAK</Text></View>
            <View style={styles.profileDivider} />
            <View style={styles.profileStat}><Text style={styles.profileStatValue}>#{data.stats.rank || '—'}</Text><Text style={styles.profileStatLabel}>RANK</Text></View>
          </View>
        </Card>

        {backendMode === 'mock' ? (
          <View style={styles.safeMode}><Ionicons name="shield-checkmark" size={20} color={colors.success} /><View style={{ flex: 1 }}><Text style={styles.safeTitle}>Safe demo mode</Text><Text style={styles.safeText}>Live backend reads and writes are disabled. All dashboard data is local sample data.</Text></View></View>
        ) : backendMode === 'live-readonly' ? (
          <View style={styles.readOnlyMode}><Ionicons name="eye-outline" size={20} color={colors.primary} /><View style={{ flex: 1 }}><Text style={styles.readOnlyTitle}>Live preview mode</Text><Text style={styles.safeText}>Displaying real backend data. Every server-side write action is blocked by the mobile API client.</Text></View></View>
        ) : (
          <View style={styles.fullLiveMode}><Ionicons name="cloud-done" size={20} color={colors.success} /><View style={{ flex: 1 }}><Text style={styles.fullLiveTitle}>Full live connection</Text><Text style={styles.safeText}>Real dashboard data is connected. Study submissions and account updates sync with the existing backend.</Text></View></View>
        )}

        {backendMode === 'live' ? <View style={[styles.pushCard, pushEnabled && styles.pushCardEnabled]}><View style={[styles.pushIcon, pushEnabled && styles.pushIconEnabled]}><Ionicons name={pushEnabled ? 'notifications' : 'notifications-outline'} size={20} color={pushEnabled ? colors.success : colors.primary} /></View><View style={{ flex: 1 }}><Text style={[styles.pushTitle, pushEnabled && { color: colors.success }]}>{pushEnabled ? 'Live notifications enabled' : 'Live notifications'}</Text><Text style={styles.pushText}>{pushMessage}</Text></View>{!pushEnabled && pushStatus !== 'requesting' ? <Pressable onPress={() => enablePush()} style={styles.pushButton}><Text style={styles.pushButtonText}>Enable</Text></Pressable> : null}</View> : null}

        {backendMode === 'live' ? (
          <View style={[styles.shareCard, progressSharing && styles.shareCardEnabled]}>
            <View style={[styles.pushIcon, progressSharing && { backgroundColor: '#FFFFFF' }]}>
              <Ionicons name={progressSharing ? 'shield-checkmark' : 'shield-outline'} size={20} color={progressSharing ? colors.success : colors.primary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[styles.shareTitle, progressSharing && { color: colors.success }]}>{progressSharing ? 'Sharing MCQ progress with mentor' : 'Share MCQ progress with mentor'}</Text>
              <Text style={styles.shareText}>
                {progressSharing
                  ? 'Your chapter-level summaries sync with your mentor. Only summaries leave this device — never raw answers.'
                  : 'Turn this on so Ujjwal Pathak can see your chapter mastery and guide you.'}
              </Text>
            </View>
            <Pressable disabled={progressBusy} onPress={() => confirmSharingToggle(!progressSharing)} style={[styles.pushButton, progressSharing && styles.shareButtonOff]}>
              <Text style={styles.pushButtonText}>{progressBusy ? 'Saving…' : progressSharing ? 'Turn off' : 'Turn on'}</Text>
            </Pressable>
          </View>
        ) : null}

        <Text style={styles.sectionTitle}>Student details</Text>
        <Card style={styles.infoCard}>
          <InfoRow icon="mail-outline" label="Email" value={student?.email} />
          <View style={styles.line} />
          <InfoRow icon="call-outline" label="Phone" value={student?.phone} />
          <View style={styles.line} />
          <InfoRow icon="calendar-outline" label="Joined on" value={student?.joinedOn} />
          <View style={styles.line} />
          <InfoRow icon="people-outline" label="Batch" value={student?.batch} />
          <View style={styles.line} />
          <InfoRow icon="flag-outline" label="Attempt" value={student?.attempt} />
        </Card>

        <Text style={styles.sectionTitle}>Account & progress</Text>
        <Card style={styles.menuCard}>
          <MenuRow icon="help-circle-outline" title="Daily MCQ Challenge" subtitle="Today’s 10-question knowledge check" onPress={() => navigation.navigate('DailyMcq')} />
          <View style={styles.line} />
          <MenuRow icon="infinite-outline" title="Unlimited MCQ Practice" subtitle="Combined, chapter-wise and difficulty-wise" onPress={() => navigation.navigate('McqPractice')} />
          <View style={styles.line} />
          <MenuRow icon="notifications-outline" title="Notifications" subtitle="Mentor updates and new material" onPress={() => navigation.navigate('Notifications')} />
          <View style={styles.line} />
          <MenuRow icon="trophy-outline" title="Leaderboard" subtitle="See your cohort position" onPress={() => navigation.navigate('Leaderboard')} />
          <View style={styles.line} />
          <MenuRow icon="bar-chart-outline" title="Weekly reports" subtitle="Review progress and mentor rating" onPress={() => navigation.navigate('Reports')} />
          {backendMode !== 'live-readonly' ? <><View style={styles.line} /><MenuRow icon="key-outline" title="Change password" subtitle={backendMode === 'live' ? 'Update your live account password' : 'Test the password-change UI safely'} onPress={() => navigation.navigate('ChangePassword')} /></> : null}
        </Card>

        <PrimaryButton label="Sign out" icon="log-out-outline" variant="secondary" onPress={confirmLogout} style={styles.logout} />
        <Text style={styles.version}>Ujjwal Pathak Mentorship · Mobile v1.10.2</Text>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.canvas },
  content: { paddingHorizontal: spacing.lg, paddingBottom: 110 },
  header: { paddingVertical: spacing.lg },
  eyebrow: { color: colors.primary, fontSize: 10, fontWeight: '900', letterSpacing: 1.3 },
  title: { color: colors.ink, fontSize: 27, fontWeight: '900', letterSpacing: -0.7, marginTop: 3 },
  profileCard: { alignItems: 'center', paddingTop: spacing.xxl, paddingBottom: 0, overflow: 'hidden', shadowOpacity: 0.05 },
  name: { color: colors.ink, fontSize: 21, fontWeight: '900', marginTop: spacing.md },
  studentId: { color: colors.muted, fontSize: 11, fontWeight: '700', marginTop: 3 },
  tags: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
  tag: { backgroundColor: colors.primarySoft, paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill },
  tagText: { color: colors.primary, fontSize: 9, fontWeight: '900' },
  groupTag: { backgroundColor: colors.tealSoft },
  groupTagText: { color: colors.teal },
  profileStats: { alignSelf: 'stretch', flexDirection: 'row', alignItems: 'center', backgroundColor: colors.canvas, marginTop: spacing.xl, paddingVertical: spacing.lg },
  profileStat: { flex: 1, alignItems: 'center' },
  profileStatValue: { color: colors.ink, fontSize: 16, fontWeight: '900' },
  profileStatLabel: { color: colors.muted, fontSize: 7, fontWeight: '900', letterSpacing: 0.5, marginTop: 3 },
  profileDivider: { height: 33, width: 1, backgroundColor: colors.border },
  safeMode: { flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start', backgroundColor: colors.tealSoft, borderRadius: radius.md, padding: spacing.md, marginTop: spacing.lg },
  safeTitle: { color: colors.success, fontSize: 12, fontWeight: '900' },
  safeText: { color: colors.inkSoft, fontSize: 10, lineHeight: 15, marginTop: 2 },
  readOnlyMode: { flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start', backgroundColor: colors.primarySoft, borderRadius: radius.md, padding: spacing.md, marginTop: spacing.lg },
  readOnlyTitle: { color: colors.primary, fontSize: 12, fontWeight: '900' },
  fullLiveMode: { flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start', backgroundColor: colors.tealSoft, borderRadius: radius.md, borderWidth: 1, borderColor: '#BFE5DB', padding: spacing.md, marginTop: spacing.lg },
  fullLiveTitle: { color: colors.success, fontSize: 12, fontWeight: '900' },
  pushCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.primarySoft, borderRadius: radius.md, borderWidth: 1, borderColor: '#D7E0FF', padding: spacing.md, marginTop: spacing.md },
  pushCardEnabled: { backgroundColor: colors.tealSoft, borderColor: '#BFE5DB' },
  pushIcon: { width: 40, height: 40, borderRadius: 13, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  pushIconEnabled: { backgroundColor: '#FFFFFF' },
  pushTitle: { color: colors.primary, fontSize: 11, fontWeight: '900' },
  pushText: { color: colors.inkSoft, fontSize: 8, lineHeight: 13, marginTop: 2 },
  pushButton: { borderRadius: radius.pill, backgroundColor: colors.primary, paddingHorizontal: 11, paddingVertical: 8 },
  pushButtonText: { color: '#FFFFFF', fontSize: 8, fontWeight: '900' },
  shareButtonOff: { backgroundColor: '#DC2626' },
  shareCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.primarySoft, borderRadius: radius.md, borderWidth: 1, borderColor: '#D7E0FF', padding: spacing.md, marginTop: spacing.md },
  shareCardEnabled: { backgroundColor: colors.tealSoft, borderColor: '#BFE5DB' },
  shareTitle: { color: colors.primary, fontSize: 11, fontWeight: '900' },
  shareText: { color: colors.inkSoft, fontSize: 8, lineHeight: 13, marginTop: 2 },
  sectionTitle: { color: colors.ink, fontSize: 17, fontWeight: '900', marginTop: spacing.xxl, marginBottom: spacing.md },
  infoCard: { paddingVertical: 3, shadowOpacity: 0.03 },
  infoRow: { flexDirection: 'row', alignItems: 'center', minHeight: 63, gap: spacing.md },
  infoIcon: { width: 38, height: 38, borderRadius: 12, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' },
  infoBody: { flex: 1 },
  infoLabel: { color: colors.muted, fontSize: 9, fontWeight: '700' },
  infoValue: { color: colors.ink, fontSize: 13, fontWeight: '800', marginTop: 3 },
  line: { height: 1, backgroundColor: colors.border, marginLeft: 51 },
  menuCard: { paddingVertical: 0, overflow: 'hidden', shadowOpacity: 0.03 },
  menuRow: { minHeight: 71, flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  menuIcon: { width: 40, height: 40, borderRadius: 13, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' },
  menuBody: { flex: 1 },
  menuTitle: { color: colors.ink, fontSize: 13, fontWeight: '900' },
  menuSubtitle: { color: colors.muted, fontSize: 9, marginTop: 3 },
  logout: { marginTop: spacing.xxl },
  version: { color: colors.muted, fontSize: 9, textAlign: 'center', marginTop: spacing.lg },
});
