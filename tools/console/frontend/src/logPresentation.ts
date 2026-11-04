import { classifyEntries, displayMessage } from "./logs";
import { conversationLines, redactLogLine, redactOperationalMessages, type Privacy } from "./privacy";
import type { LogEntry } from "./types";

/** フィルタや件数制限の前に保持行全体を分類し、伏せ字を適用する。 */
export function prepareLogEntries(entries: LogEntry[], privacy: Privacy) {
  const levels = classifyEntries(entries);
  const conversation = conversationLines(entries);
  const messages = redactOperationalMessages(entries.map(displayMessage), privacy);
  return entries.map((entry, index) => ({
    entry,
    level: levels[index],
    text: redactLogLine(messages[index], conversation[index], privacy),
  }));
}
