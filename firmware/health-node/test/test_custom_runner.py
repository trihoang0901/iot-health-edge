from platformio.public import TestCase, TestRunnerBase, TestStatus


class CustomTestRunner(TestRunnerBase):
    """Treat each assert-based native executable as one PlatformIO test case."""

    def stage_testing(self):
        super().stage_testing()
        self.test_suite.add_case(
            TestCase(
                name=self.test_suite.test_name,
                status=TestStatus.PASSED,
            )
        )
