import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AppUpdateProvider } from './src/context/AppUpdateContext';
import { AuthProvider } from './src/context/AuthContext';
import { DailyMcqProvider } from './src/context/DailyMcqContext';
import { DataProvider } from './src/context/DataContext';
import { FocusTimerProvider } from './src/context/FocusTimerContext';
import { McqBankProvider } from './src/context/McqBankContext';
import { McqPracticeProvider } from './src/context/McqPracticeContext';
import { NotificationsProvider } from './src/context/NotificationsContext';
import { ProgressSyncProvider } from './src/context/ProgressSyncContext';
import { StudyReceiptsProvider } from './src/context/StudyReceiptContext';
import { AppNavigator } from './src/navigation/AppNavigator';

export default function App() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <AuthProvider>
          <AppUpdateProvider>
            <DataProvider>
              <FocusTimerProvider>
                <StudyReceiptsProvider>
                  <McqBankProvider>
                    <DailyMcqProvider>
                      <McqPracticeProvider>
                        <ProgressSyncProvider>
                          <NotificationsProvider>
                            <StatusBar style="dark" />
                            <AppNavigator />
                          </NotificationsProvider>
                        </ProgressSyncProvider>
                      </McqPracticeProvider>
                    </DailyMcqProvider>
                  </McqBankProvider>
                </StudyReceiptsProvider>
              </FocusTimerProvider>
            </DataProvider>
          </AppUpdateProvider>
        </AuthProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
