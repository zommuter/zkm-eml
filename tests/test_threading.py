"""Tests for threading.py — thread_id derivation."""

from __future__ import annotations

from zkm_eml.threading import thread_id_for


def test_thread_id_no_references():
    tid = thread_id_for("abc@example.com", [])
    assert len(tid) == 16
    assert tid.isalnum()


def test_thread_id_uses_oldest_reference():
    # Thread root is the first (oldest) reference
    tid_root = thread_id_for("root@example.com", [])
    tid_child = thread_id_for("child@example.com", ["root@example.com"])
    tid_grandchild = thread_id_for("grandchild@example.com", ["root@example.com", "child@example.com"])
    # All should share the same thread_id
    assert tid_root == tid_child == tid_grandchild


def test_thread_id_is_stable():
    tid1 = thread_id_for("msg@example.com", ["root@example.com"])
    tid2 = thread_id_for("msg@example.com", ["root@example.com"])
    assert tid1 == tid2


def test_thread_id_different_roots_differ():
    tid_a = thread_id_for("msg@example.com", ["root-a@example.com"])
    tid_b = thread_id_for("msg@example.com", ["root-b@example.com"])
    assert tid_a != tid_b


def test_thread_id_broken_references_falls_back_to_own_id():
    # If references is empty, own message_id determines the thread
    tid = thread_id_for("orphan@example.com", [])
    assert len(tid) == 16
