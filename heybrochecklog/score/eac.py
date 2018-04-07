"""This module contains the EAC Log Checker."""

import re
from heybrochecklog.markup import markup
from heybrochecklog.score.logchecker import LogChecker
from heybrochecklog import UnrecognizedException
from heybrochecklog.score.modules import combined, parsers, validation


class EACChecker(LogChecker):
    """This class analyzes >0.95 EAC Log Files."""

    def check(self, main_log):
        """Checks the EAC logs."""
        logs = combined.split_combined(main_log)
        for log in logs:
            if len(log.concat_contents) < 20:
                raise UnrecognizedException('Cannot parse log file; log file too short')

            log.version = self.check_version(log)
            log.album = log.concat_contents[2]
            log.drive = self.check_drive(log)

            self.index_log(log)
            self.evaluate_settings(log)
            parsers.index_toc(log)
            self.is_there_a_htoa(log)
            self.check_tracks(log)
            parsers.parse_checksum(log, self.patterns['checksum'], 'V1.0 beta 1', 'EAC <1.0')
            markup(log, self.patterns, self.translation)

        main_log = combined.defragment(logs)
        validation.validate_track_count(main_log)
        validation.validate_track_settings(main_log)
        self.deduct_and_score(main_log)

        return main_log

    def check_version(self, log):
        """Check the version of the log and verify it is acceptable."""
        regex = re.compile(r'Exact Audio Copy (V.*) from (.*)')
        return self.verify_version(regex, log.concat_contents[0], 'EAC')

    def check_drive(self, log):
        """Check the drive of the log and verify it is an allowed drive."""
        regex = r' ?: (.*) Adapter:[ 0-9]+ID:[ 0-9]+$'
        return self.get_drive(regex, log.concat_contents[3])

    def all_range_index(self, log, line):
        """Match the Range Rip line in the log file."""
        if log.index_tracks is None and re.match(self.patterns['range'], line):
            return True
        return False

    def all_range_index_action(self, log, line_num):
        """Action to take when the range rip line is matched."""
        log.track_indices.append(line_num)
        log.range = True

    def check_bad_settings(self, log, line):
        """Evaluate the instant -100 point deductions."""
        bad_settings = self.patterns['bad settings']
        for sett, pattern in bad_settings.items():
            if pattern in line:
                log.add_deduction(sett)

    def is_there_a_htoa(self, log):
        """Check rip for Hidden Track One Audio."""
        # 6 second minimum for HTOA per EAC standards
        # Only accepted HTOA extraction technique for EAC is range-based
        if log.toc[1][0] < 450 or not log.range:
            return

        for line in log.contents[log.index_tracks + 1:]:
            if line.strip():
                result = re.search(self.patterns['htoa'], line)
                if result:
                    log.htoa = True
                    log.htoa_index = log.toc[1][0] - 1

                    # Remove the gap handling notification (doesn't appear for range rips)
                    if log.has_deduction('Could not verify gap handling'):
                        log.remove_deduction('Could not verify gap handling')

                    if int(result.group(1)) == log.htoa_index:
                        log.htoa_ripped = True
                        log.add_deduction('HTOA extracted')
                    else:
                        log.add_deduction('Improper HTOA extraction')
                else:
                    log.add_deduction('HTOA detected, but not extracted')
                break

    def check_tracks(self, log):
        """Wrapper for the analyze_tracks method. Get track data for every track
        and check for errors.
        """
        tsettings = self.patterns['track settings']
        track_settings = {
            'filename': re.compile(r'\s+' + tsettings['filename'] + r' (.*)'),
            'pregap': re.compile(r'\s+' + tsettings['pregap'] + r' ([0-9:\.]+)'),
            'peak': re.compile(r'\s+' + tsettings['peak'] + r' ([0-9\.]+) %'),
            'test crc': re.compile(r'\s+' + tsettings['test crc'] + r' ([A-Z0-9]{8})'),
            'copy crc': re.compile(r'\s+' + tsettings['copy crc'] + r' ([A-Z0-9]{8})')
        }

        self.analyze_tracks(log, track_settings, parsers.parse_errors_eac)

    def evaluate_tracks(self, log):
        """Evaluate the analyzed track data for deficiencies."""
        # AccurateRip for EAC Range Rip - AR results are at the bottom of the log.
        if log.range:
            patterns = self.patterns['range accuraterip'].items()
            parsers.parse_range_accuraterip(log, patterns)

        # HTOA doesn't need these deductions, since it's supposed to be range ripping.
        if not log.htoa:
            if log.range:
                log.add_deduction('Range rip')
            # Check AccurateRip - Mismatching AR results can indicate problems even with T&C
            validation.analyze_accuraterip(log)

    def deduct_and_score(self, log):
        """Process the accumulated deductions and score the log file."""
        # Deduct for all the per-track accumulated deductions.
        for error in log.track_errors:
            if log.track_errors[error]:
                log.add_deduction(error, len(log.track_errors[error]))

        super().deduct_and_score(log)