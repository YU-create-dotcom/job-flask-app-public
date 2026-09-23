// ISO date strings compare without UTC/local timezone conversion.
function eventOccursOnDate(event, date) {
    if (!event.date || date < event.date) return false;
    if (!event.end_date || event.end_date < event.date) return date === event.date;
    // Timed ranges end exclusively: an event ending at midnight does not
    // occupy the following day. Date-only ranges include their final date.
    if (event.end_time === "00:00" && event.end_date > event.date) {
        return date < event.end_date;
    }
    return date <= event.end_date;
}

if (typeof module !== "undefined") module.exports = { eventOccursOnDate };
