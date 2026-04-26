import Foundation
import UserNotifications

enum ReminderManager {
    static let reminderEnabledKey = "snoke.reminder.enabled"
    static let reminderHourKey = "snoke.reminder.hour"
    static let reminderMinuteKey = "snoke.reminder.minute"
    static let reminderRequestID = "snoke.daily.checkin"

    static func requestPermission() async -> Bool {
        do {
            return try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound])
        } catch {
            return false
        }
    }

    static func scheduleDailyReminder(hour: Int, minute: Int) async {
        let center = UNUserNotificationCenter.current()
        await center.removePendingNotificationRequests(withIdentifiers: [reminderRequestID])

        var components = DateComponents()
        components.hour = hour
        components.minute = minute

        let trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: true)
        let content = UNMutableNotificationContent()
        content.title = "Snoke Check-in"
        content.body = "How is your craving level today? Log a quick check-in."
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: reminderRequestID,
            content: content,
            trigger: trigger
        )

        do {
            try await center.add(request)
        } catch {
            // Best effort only for MVP notification setup.
        }
    }

    static func disableReminder() async {
        await UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [reminderRequestID])
    }
}
