import { Ionicons } from '@expo/vector-icons';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import React, { useMemo, useState } from 'react';
import { Alert, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { EmptyState } from '../components/ui';
import { useData } from '../context/DataContext';
import { AppNotification, NotificationType, useNotifications } from '../context/NotificationsContext';
import type { RootStackParamList } from '../navigation/types';
import { colors, radius, spacing } from '../theme';

type Props = NativeStackScreenProps<RootStackParamList, 'Notifications'>;
type Filter = 'all' | 'unread';

const typeStyle: Record<NotificationType, { icon: keyof typeof Ionicons.glyphMap; tint: string; soft: string }> = {
  announcement: { icon: 'megaphone', tint: colors.primary, soft: colors.primarySoft },
  mentor: { icon: 'chatbubble-ellipses', tint: colors.purple, soft: colors.purpleSoft },
  material: { icon: 'document-text', tint: colors.red, soft: colors.redSoft },
  report: { icon: 'analytics', tint: colors.teal, soft: colors.tealSoft },
  feedback: { icon: 'mail-unread', tint: '#B36A16', soft: colors.amberSoft },
  memory: { icon: 'refresh-circle', tint: colors.purple, soft: colors.purpleSoft },
  mcq: { icon: 'help-circle', tint: colors.primary, soft: colors.primarySoft },
};

export const NotificationsScreen = ({ navigation }: Props) => {
  const { refreshing, refreshAll } = useData();
  const { notifications, unreadCount, pushStatus, isRead, markRead, markAllRead, clearAll, isCleared } = useNotifications();
  const [filter, setFilter] = useState<Filter>('all');
  const visible = useMemo(() => filter === 'unread' ? notifications.filter((item) => !isRead(item.id)) : notifications, [filter, isRead, notifications]);

  const open = async (item: AppNotification) => {
    await markRead(item.id);
    if (item.target === 'receipt' && item.sessionId) navigation.navigate('StudyReceipt', { sessionId: item.sessionId });
    else if (item.target === 'mcq') navigation.navigate('DailyMcq', item.group ? { group: item.group } : undefined);
    else if (item.target === 'reports') navigation.navigate('Reports');
    else if (item.target === 'notes') navigation.navigate('Main', { screen: 'Notes' });
    else navigation.navigate('Main', { screen: 'Home' });
  };

  const confirmClearAll = () => {
    Alert.alert('Clear all notifications?', 'They will not return after refresh.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Clear All', style: 'destructive', onPress: () => clearAll() },
    ]);
  };

  return (
    <SafeAreaView style={styles.safe} edges={['bottom']}>
      <FlatList
        data={visible}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => refreshAll().catch(() => undefined)} colors={[colors.primary]} />}
        ListHeaderComponent={
          <>
            <View style={styles.summary}>
              <View style={styles.summaryIcon}><Ionicons name="notifications" size={25} color={colors.primary} /></View>
              <View style={styles.summaryBody}><Text style={styles.summaryValue}>{unreadCount ? `${unreadCount} unread` : 'You’re all caught up'}</Text><Text style={styles.summaryText}>Mentor updates, reports and new material</Text></View>
              {unreadCount ? <Pressable onPress={() => markAllRead()} style={styles.markAll}><Text style={styles.markAllText}>Mark all read</Text></Pressable> : null}
              <Pressable onPress={confirmClearAll} style={[styles.markAll, { backgroundColor: '#FEE2E2' }]}><Text style={[styles.markAllText, { color: '#DC2626' }]}>Clear All</Text></Pressable>
            </View>
            <View style={styles.filters}>
              <Pressable onPress={() => setFilter('all')} style={[styles.filter, filter === 'all' && styles.filterActive]}><Text style={[styles.filterText, filter === 'all' && styles.filterTextActive]}>All</Text></Pressable>
              <Pressable onPress={() => setFilter('unread')} style={[styles.filter, filter === 'unread' && styles.filterActive]}><Text style={[styles.filterText, filter === 'unread' && styles.filterTextActive]}>Unread {unreadCount ? `(${unreadCount})` : ''}</Text></Pressable>
            </View>
          </>
        }
        renderItem={({ item }) => {
          const tone = typeStyle[item.type];
          const read = isRead(item.id);
          return (
            <Pressable onPress={() => open(item)} style={({ pressed }) => [styles.item, !read && styles.itemUnread, pressed && styles.pressed]}>
              <View style={[styles.itemIcon, { backgroundColor: tone.soft }]}><Ionicons name={tone.icon} size={21} color={tone.tint} /></View>
              <View style={styles.itemBody}>
                <View style={styles.itemTop}><Text style={[styles.itemTitle, !read && styles.unreadTitle]} numberOfLines={2}>{item.title}</Text>{!read ? <View style={styles.unreadDot} /> : null}</View>
                {item.body ? <Text style={styles.itemText} numberOfLines={3}>{item.body}</Text> : null}
                <Text style={styles.itemDate}>{item.date}</Text>
              </View>
              <Ionicons name="chevron-forward" size={17} color={colors.muted} />
            </Pressable>
          );
        }}
        ListEmptyComponent={<View style={styles.empty}><EmptyState icon={filter === 'unread' ? 'checkmark-done-circle-outline' : 'notifications-off-outline'} title={filter === 'unread' ? 'No unread notifications' : 'No notifications yet'} message={filter === 'unread' ? 'You have seen every update.' : 'New mentorship updates will appear here.'} /></View>}
        ListFooterComponent={<View style={styles.footer}><Ionicons name={pushStatus === 'enabled' ? 'notifications' : 'phone-portrait-outline'} size={16} color={pushStatus === 'enabled' ? colors.success : colors.muted} /><Text style={styles.footerText}>{pushStatus === 'enabled' ? 'Native background alerts are active on this device.' : 'In-app alerts are active. Enable native background alerts from Profile after Firebase setup.'}</Text></View>}
      />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.canvas },
  content: { padding: spacing.lg, paddingBottom: 40 },
  summary: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.primarySoft, borderRadius: radius.lg, padding: spacing.lg },
  summaryIcon: { width: 49, height: 49, borderRadius: 16, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  summaryBody: { flex: 1 },
  summaryValue: { color: colors.ink, fontSize: 14, fontWeight: '900' },
  summaryText: { color: colors.muted, fontSize: 9, marginTop: 3 },
  markAll: { paddingVertical: 7, paddingHorizontal: 9, borderRadius: radius.pill, backgroundColor: '#FFFFFF' },
  markAllText: { color: colors.primary, fontSize: 8, fontWeight: '900' },
  filters: { flexDirection: 'row', gap: spacing.sm, marginVertical: spacing.xl },
  filter: { paddingHorizontal: 15, paddingVertical: 9, borderRadius: radius.pill, backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: colors.border },
  filterActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  filterText: { color: colors.inkSoft, fontSize: 11, fontWeight: '800' },
  filterTextActive: { color: '#FFFFFF' },
  item: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: 'rgba(255,255,255,0.78)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.95)', borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.sm },
  itemUnread: { backgroundColor: '#F8FAFF', borderColor: '#C9D4FA' },
  pressed: { opacity: 0.78, transform: [{ scale: 0.995 }] },
  itemIcon: { width: 44, height: 44, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  itemBody: { flex: 1 },
  itemTop: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  itemTitle: { flex: 1, color: colors.inkSoft, fontSize: 12, fontWeight: '700', lineHeight: 17 },
  unreadTitle: { color: colors.ink, fontWeight: '900' },
  unreadDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.primary, marginTop: 4 },
  itemText: { color: colors.muted, fontSize: 10, lineHeight: 15, marginTop: 4 },
  itemDate: { color: colors.muted, fontSize: 8, fontWeight: '700', marginTop: 6 },
  empty: { marginTop: spacing.xxl },
  footer: { flexDirection: 'row', justifyContent: 'center', alignItems: 'flex-start', gap: spacing.sm, marginTop: spacing.xxl, paddingHorizontal: spacing.xl },
  footerText: { flex: 1, color: colors.muted, fontSize: 8, lineHeight: 13, textAlign: 'center' },
});
