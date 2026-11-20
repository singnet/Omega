(skill test-skill "Test skill to demonstrate workflow by sending message to the user" (message))

(= (test-skill $message)
   (send $message))
