from __future__ import annotations

import unittest

from api.session_auth import InMemoryTokenBindingStore


class SessionAuthTests(unittest.TestCase):
    def test_first_token_binds_and_only_matching_token_authenticates(self):
        store = InMemoryTokenBindingStore()
        token = "a" * 32

        self.assertTrue(store.authenticate_or_bind("user-1", token))
        self.assertTrue(store.authenticate_or_bind("user-1", token))
        self.assertFalse(store.authenticate_or_bind("user-1", "b" * 32))

    def test_store_contains_hash_and_salt_but_not_raw_token(self):
        store = InMemoryTokenBindingStore()
        token = "secret-anonymous-token-value-1234"
        store.authenticate_or_bind("user-1", token)

        binding = store._bindings["user-1"]
        self.assertNotEqual(binding.token_hash, token.encode())
        self.assertNotIn(token, repr(binding))
        self.assertEqual(len(binding.salt), 16)
        self.assertEqual(len(binding.token_hash), 32)

    def test_delete_removes_binding(self):
        store = InMemoryTokenBindingStore()
        store.authenticate_or_bind("user-1", "a" * 32)
        self.assertTrue(store.delete("user-1"))
        self.assertFalse(store.delete("user-1"))


if __name__ == "__main__":
    unittest.main()
