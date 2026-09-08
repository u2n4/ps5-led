import math

from controller_gl import Orbit, Orientation


def sample(timestamp, **values):
    return dict(connected=True, sensor_timestamp=timestamp,
                gyro=values.get("gyro", (0, 0, 0)),
                accel=values.get("accel", (0.001, 0.962, 0.152)),
                right_stick=values.get("right_stick", (0, 0)))


def test_measured_desk_gravity_converges_near_nine_degrees_not_eighty_one():
    orientation = Orientation()
    for _ in range(600):
        q = orientation.update((0, 0, 0), (0.001, 0.962, 0.152), 0.004)
    roll = math.degrees(math.atan2(2*(q[3]*q[0]+q[1]*q[2]),
                                   1-2*(q[0]*q[0]+q[1]*q[1])))
    assert 8.8 < roll < 9.2


def test_rest_never_moves_default_camera_and_deadzone_covers_measured_drift():
    orbit = Orbit()
    for i in range(120):
        orbit.update(sample(i*100000, right_stick=(0.109, -0.02)), i/30)
    assert orbit.rotation == (0, 0, 0, 1)


def test_mouse_wins_over_gyro_and_stick_and_release_has_no_accumulated_jump():
    orbit = Orbit()
    orbit.gyro_enabled = True
    orbit.dragging = True
    for i in range(30):
        orbit.update(sample(i*100000, gyro=(0, 30, 0), right_stick=(1, 0)), i/30)
    assert orbit.rotation == (0, 0, 0, 1)
    orbit.rotate(30, 20)
    before = orbit.rotation
    orbit.dragging = False
    orbit.update(sample(2900000), 29/30)
    assert orbit.rotation == before


def test_right_stick_orbits_but_stale_input_cannot_keep_rotating():
    orbit = Orbit()
    orbit.update(sample(0, right_stick=(1, 0)), 0)
    orbit.update(sample(100000, right_stick=(1, 0)), 1/30)
    assert orbit.rotation != (0, 0, 0, 1)
    before = orbit.rotation
    orbit.update(sample(100000, right_stick=(1, 0)), 1)
    assert orbit.rotation == before
    orbit.reset()
    assert orbit.rotation == (0, 0, 0, 1)


def test_disabled_stick_does_not_block_enabled_gyro():
    orbit = Orbit()
    orbit.stick_enabled = False
    orbit.gyro_enabled = True
    orbit.update(sample(0, right_stick=(1, 0)), 0)
    orbit.update(sample(100000, gyro=(20, 0, 0), right_stick=(1, 0)), 1/30)
    assert orbit.rotation != (0, 0, 0, 1)
