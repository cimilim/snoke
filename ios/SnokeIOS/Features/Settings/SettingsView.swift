import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var config: AppConfig
    @State private var backendURL = ""
    @State private var savedMessage: String?
    @State private var remindersEnabled = UserDefaults.standard.bool(forKey: ReminderManager.reminderEnabledKey)
    @State private var reminderHour = UserDefaults.standard.integer(forKey: ReminderManager.reminderHourKey)
    @State private var reminderMinute = UserDefaults.standard.integer(forKey: ReminderManager.reminderMinuteKey)
    @State private var reminderInfoMessage: String?

    private var reminderDate: Binding<Date> {
        Binding<Date>(
            get: {
                var components = DateComponents()
                components.hour = reminderHour == 0 ? 20 : reminderHour
                components.minute = reminderMinute
                return Calendar.current.date(from: components) ?? Date()
            },
            set: { date in
                let comps = Calendar.current.dateComponents([.hour, .minute], from: date)
                reminderHour = comps.hour ?? 20
                reminderMinute = comps.minute ?? 0
            }
        )
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Backend") {
                    TextField("https://api.example.com", text: $backendURL)
                        .autocorrectionDisabled()

                    Button("Save backend URL") {
                        config.setBackendURL(backendURL)
                        savedMessage = "Saved. Restart app requests with new backend."
                    }
                }

                if let savedMessage {
                    Section {
                        Text(savedMessage).foregroundStyle(.green)
                    }
                }

                Section("Reminders") {
                    Toggle("Daily check-in reminder", isOn: $remindersEnabled)
                        .onChange(of: remindersEnabled) { newValue in
                            Task { await handleReminderToggle(newValue) }
                        }

                    DatePicker("Reminder time", selection: reminderDate, displayedComponents: .hourAndMinute)
                        .onChange(of: reminderHour) { _ in
                            Task { await persistReminderTimeAndRescheduleIfNeeded() }
                        }
                        .onChange(of: reminderMinute) { _ in
                            Task { await persistReminderTimeAndRescheduleIfNeeded() }
                        }

                    if let reminderInfoMessage {
                        Text(reminderInfoMessage).font(.footnote).foregroundStyle(.secondary)
                    }
                }

                Section("Session") {
                    if let device = session.deviceID {
                        Text("Device: \(device)").font(.footnote)
                    }
                    Button("Logout", role: .destructive) {
                        session.logout()
                    }
                }
            }
            .navigationTitle("Settings")
            .onAppear {
                backendURL = config.backendURL
                if reminderHour == 0 && reminderMinute == 0 {
                    reminderHour = 20
                }
            }
        }
    }

    private func handleReminderToggle(_ enabled: Bool) async {
        UserDefaults.standard.set(enabled, forKey: ReminderManager.reminderEnabledKey)
        if enabled {
            let granted = await ReminderManager.requestPermission()
            if granted {
                await ReminderManager.scheduleDailyReminder(hour: reminderHour, minute: reminderMinute)
                reminderInfoMessage = "Reminder is active."
            } else {
                remindersEnabled = false
                UserDefaults.standard.set(false, forKey: ReminderManager.reminderEnabledKey)
                reminderInfoMessage = "Notifications denied. Enable them in iOS Settings."
            }
        } else {
            await ReminderManager.disableReminder()
            reminderInfoMessage = "Reminder disabled."
        }
    }

    private func persistReminderTimeAndRescheduleIfNeeded() async {
        UserDefaults.standard.set(reminderHour, forKey: ReminderManager.reminderHourKey)
        UserDefaults.standard.set(reminderMinute, forKey: ReminderManager.reminderMinuteKey)
        if remindersEnabled {
            await ReminderManager.scheduleDailyReminder(hour: reminderHour, minute: reminderMinute)
            reminderInfoMessage = String(format: "Reminder set for %02d:%02d.", reminderHour, reminderMinute)
        }
    }
}
