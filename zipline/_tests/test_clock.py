from datetime import time
from unittest import TestCase
import pandas as pd
from pandas.testing import assert_index_equal
from zipline.utils.calendar_utils import get_calendar, days_at_time

from zipline.gens.sim_engine import (
    MinuteSimulationClock,
    SESSION_START,
    BEFORE_TRADING_START_BAR,
    BAR,
    SESSION_END
)


class TestClock(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nyse_calendar = get_calendar("NYSE")

        # july 15 is friday, so there are 3 sessions in this range (15, 18, 19)
        cls.sessions = cls.nyse_calendar.sessions_in_range(
            pd.Timestamp("2016-07-15"),
            pd.Timestamp("2016-07-19")
        )

        cls.opens = cls.nyse_calendar.first_minutes.loc[cls.sessions]
        cls.closes = cls.nyse_calendar.schedule.loc[
            cls.sessions, "close"
        ]

        cls.break_starts = cls.nyse_calendar.last_am_minutes.loc[cls.sessions]
        cls.break_ends = cls.nyse_calendar.first_pm_minutes.loc[cls.sessions]

    def test_bts_before_session(self):
        clock = MinuteSimulationClock(
            self.sessions,
            self.opens,
            self.closes,
            days_at_time(self.sessions, time(6, 17), "US/Eastern", day_offset=0),
            self.break_starts,
            self.break_ends,
            False
        )

        all_events = list(clock)

        def _check_session_bts_first(session_label, events, bts_dt):
            minutes = self.nyse_calendar.session_minutes(session_label)

            self.assertEqual(393, len(events))

            self.assertEqual(events[0], (session_label.tz_localize("UTC"), SESSION_START))
            self.assertEqual(events[1], (bts_dt, BEFORE_TRADING_START_BAR))
            for i in range(2, 392):
                self.assertEqual(events[i], (minutes[i - 2], BAR))
            self.assertEqual(events[392], (minutes[-1], SESSION_END))

        _check_session_bts_first(
            self.sessions[0],
            all_events[0:393],
            pd.Timestamp("2016-07-15 6:17", tz='US/Eastern')
        )

        _check_session_bts_first(
            self.sessions[1],
            all_events[393:786],
            pd.Timestamp("2016-07-18 6:17", tz='US/Eastern')
        )

        _check_session_bts_first(
            self.sessions[2],
            all_events[786:],
            pd.Timestamp("2016-07-19 6:17", tz='US/Eastern')
        )

    def test_bts_during_session(self):
        self.verify_bts_during_session(
            time(11, 45), [
                pd.Timestamp("2016-07-15 11:45", tz='US/Eastern'),
                pd.Timestamp("2016-07-18 11:45", tz='US/Eastern'),
                pd.Timestamp("2016-07-19 11:45", tz='US/Eastern')
            ],
            135
        )

    def test_bts_on_first_minute(self):
        self.verify_bts_during_session(
            time(9, 30), [
                pd.Timestamp("2016-07-15 9:30", tz='US/Eastern'),
                pd.Timestamp("2016-07-18 9:30", tz='US/Eastern'),
                pd.Timestamp("2016-07-19 9:30", tz='US/Eastern')
            ],
            1
        )

    def test_bts_on_last_minute(self):
        self.verify_bts_during_session(
            time(16, 00), [
                pd.Timestamp("2016-07-15 16:00", tz='US/Eastern'),
                pd.Timestamp("2016-07-18 16:00", tz='US/Eastern'),
                pd.Timestamp("2016-07-19 16:00", tz='US/Eastern')
            ],
            390
        )

    def verify_bts_during_session(self, bts_time, bts_session_times, bts_idx):
        def _check_session_bts_during(session_label, events, bts_dt):
            minutes = self.nyse_calendar.session_minutes(session_label)

            self.assertEqual(393, len(events))

            self.assertEqual(events[0], (session_label.tz_localize("UTC"), SESSION_START))

            for i in range(1, bts_idx):
                self.assertEqual(events[i], (minutes[i - 1], BAR))

            self.assertEqual(
                events[bts_idx],
                (bts_dt, BEFORE_TRADING_START_BAR)
            )

            for i in range(bts_idx + 1, 391):
                self.assertEqual(events[i], (minutes[i - 2], BAR))

            self.assertEqual(events[392], (minutes[-1], SESSION_END))

        clock = MinuteSimulationClock(
            self.sessions,
            self.opens,
            self.closes,
            days_at_time(self.sessions, bts_time, "US/Eastern", day_offset=0),
            self.break_starts,
            self.break_ends,
            False
        )

        all_events = list(clock)

        _check_session_bts_during(
            self.sessions[0],
            all_events[0:393],
            bts_session_times[0]
        )

        _check_session_bts_during(
            self.sessions[1],
            all_events[393:786],
            bts_session_times[1]
        )

        _check_session_bts_during(
            self.sessions[2],
            all_events[786:],
            bts_session_times[2]
        )

    def test_bts_after_session(self):
        clock = MinuteSimulationClock(
            self.sessions,
            self.opens,
            self.closes,
            days_at_time(self.sessions, time(19, 5), "US/Eastern", day_offset=0),
            self.break_starts,
            self.break_ends,
            False
        )

        all_events = list(clock)

        # since 19:05 Eastern is after the NYSE is closed, we don't emit
        # BEFORE_TRADING_START.  therefore, each day has SESSION_START,
        # 390 BARs, and then SESSION_END

        def _check_session_bts_after(session_label, events):
            minutes = self.nyse_calendar.session_minutes(session_label)

            self.assertEqual(392, len(events))
            self.assertEqual(events[0], (session_label.tz_localize("UTC"), SESSION_START))

            for i in range(1, 391):
                self.assertEqual(events[i], (minutes[i - 1], BAR))

            self.assertEqual(events[-1], (minutes[389], SESSION_END))

        for i in range(0, 2):
            _check_session_bts_after(
                self.sessions[i],
                all_events[(i * 392): ((i + 1) * 392)]
            )

    def test_market_breaks(self):

        calendar = get_calendar("XTKS")

        sessions = calendar.sessions_in_range(
            pd.Timestamp("2021-06-14"),
            pd.Timestamp("2021-06-15")
        )

        opens = calendar.first_minutes.loc[sessions]
        closes = calendar.schedule.loc[
            sessions, "close"
        ]

        break_starts = calendar.last_am_minutes.loc[sessions]
        break_ends = calendar.first_pm_minutes.loc[sessions]

        clock = MinuteSimulationClock(
            sessions,
            opens,
            closes,
            days_at_time(sessions, time(8, 45), "Japan", day_offset=0),
            break_starts,
            break_ends,
            False
        )

        all_events = list(clock)
        all_events = pd.DataFrame(all_events, columns=["date", "event"]).set_index("date")
        bar_events = all_events[all_events.event == BAR]

        # XTKS is open 9am - 3pm with a 1 hour lunch break from 11:30am - 12:30pm
        # 2 days x 300 minutes per day
        self.assertEqual(len(bar_events), 600)

        assert_index_equal(
            bar_events.tz_convert("Japan").iloc[148:152].index,
            pd.DatetimeIndex(
                ['2021-06-14 11:29:00',
                '2021-06-14 11:30:00',
                '2021-06-14 12:31:00',
                '2021-06-14 12:32:00'], tz="Japan", name="date")
        )
