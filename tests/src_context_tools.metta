!(import! &self ./tests/lib/utils)
!(import! &self ../src/helper.py)
!(import! &self ../plugins/context/frame_helpers.py)
!(import! &self ../src/providers.py)
!(import! &self ./lib/frame_tools.py)
!(import! &self ../src/utils)
!(assertaPredicate (Predicate (library_path (projectRootDirectory))))
!(import! &self ../src/logger.py)
!(import! &self ../src/log)
!(import! &self ../src/skills)
!(import! &self ../plugins/context/contextframe)
!(import! &self ../plugins/context/contextframeskill)
!(import! &self ../src/context_provider)
!(import! &self ../src/loop)

!(register-context-frame-skills)

; This test exercises tool recording without running frame initialization.
(= (maxFrameHistoryEvents) 100)
!(change-state! &cfv2-current-frame-id FrameToolTest)
!(change-state! &cfv2-current-results ())
!(change-state! &cfv2-current-history-summary "")
!(change-state! &cfv2-frame-event-space ())
!(change-state! &cfv2-frame-prune-space ())

; Exercise registered tool schema -> provider response -> MeTTa execution -> history.
!(let $calls (sread (py-call (frame_tools.result_call (collectTools))))
   (collapse (let ($callID $command) (superpose $calls) (eval $command))))
!(test (contains-text (repr (get-state &cfv2-current-results)) "frame tool result") True)
!(test (contains-text (get-state &cfv2-current-history-summary) "Observation/ResultAdded") True)
!(test (py-call (frame_tools.has_completion_tool (collectTools))) True)
!(test (py-call (frame_tools.has_all_frame_tools (collectTools))) True)

; Tool arguments are strings; stored relation IDs are symbols.
!(change-state! &cfv2-relational-space
   ((Relation (FrameID-1 FrameA) (FrameID-2 FrameB)
      (Class ContinuationOf) (Reason "follow-up") (Confidence 0.92))))
!(test (show-frame-relation FrameA) (get-state &cfv2-relational-space))
!(test (show-frame-relation "FrameA") (get-state &cfv2-relational-space))
!(test (show-frame-relation FrameB) (get-state &cfv2-relational-space))
!(test (show-frame-relation "FrameB") (get-state &cfv2-relational-space))
!(test (show-frame-relation UnknownFrame) ())
!(test (show-frame-relation "UnknownFrame") ())

; Composition reads actual frame content without changing ownership or status.
!(cfv2-init-context-frames)

(= (test-composition-frame $id $status)
   (test-composition-frame $id $status "earlier planning decisions" "day two exercises"))

(= (test-composition-frame $id $status $history $results)
   (Frame (frameID $id) (parent-frameID ()) (source UserDirective) (priority 1.0)
      (goal-namespace $id) (status $status) (frame-mode Fast)
      (hypotheses ()) (method ()) (history-summary $history)
      (modules ()) (budget ()) (constraints ("beginner audience"))
      (deliverables ("existing onboarding plan")) (sub-frame-namespace ())
      (results ($results)) (created-at ()) (updated-at ())
      (completed-timestamp ()) (completed-summary "plan delivered")))

!(change-state! FrameA ((Goal (frameID FrameA) (description "prepare plan") (status Active))))
!(change-state! &cfv2-active-framespace
   ((test-composition-frame FrameB Active) (test-composition-frame FrameA Active)
    (test-composition-frame SeparateFrame Active)))
!(change-state! &cfv2-relational-space
   ((Relation (FrameID-1 FrameB) (FrameID-2 FrameA) (Class ContinuationOf) (Reason "continue") (Confidence 0.9))
    (Relation (FrameID-1 FrameB) (FrameID-2 FrameA) (Class FollowUp) (Reason "duplicate target") (Confidence 0.8))
    (Relation (FrameID-1 FrameB) (FrameID-2 FrameB) (Class FollowUp) (Reason "self") (Confidence 0.9))
    (Relation (FrameID-1 SeparateFrame) (FrameID-2 FrameB) (Class FollowUp) (Reason "incoming") (Confidence 0.9))
    (Relation (FrameID-1 FrameB) (FrameID-2 SeparateFrame) (Class RelatedButSeparate) (Reason "separate work") (Confidence 0.9))
    (Relation (FrameID-1 FrameA) (FrameID-2 SeparateFrame) (Class FollowUp) (Reason "indirect") (Confidence 0.9))
    (Relation (FrameID-1 FrameB) (FrameID-2 MissingFrame) (Class FollowUp) (Reason "old sketch") (Confidence 0.9))))
!(cfv2-clear-current-frame-cache)
!(change-state! &cfv2-root-mode Fast)
!(cfv2-load-frame FrameB)
!(change-state! &composition-active-before (cfv2ActiveFrameSpace))
!(change-state! &composition-completed-before (cfv2CompletedFrameSpace))
!(change-state! &composition-goals-before (get-state FrameA))

!(test (size-atom (cfv2-related-frames-for-prompt)) 1)
!(test (contains-text (repr (cfv2-context-projection)) "RelatedFrames") True)
!(test (contains-text (repr (cfv2-related-frames-for-prompt)) "FrameA") True)
!(test (contains-text (repr (cfv2-related-frames-for-prompt)) "SeparateFrame") False)
!(test (contains-text (repr (cfv2-related-frames-for-prompt)) "MissingFrame") False)
!(test
   (let $longText (py-call (.__mul__ "long observation " 1000))
      (< (string_length (repr (cfv2-related-frame-content
            (test-composition-frame FrameA Active $longText $longText) (ContinuationOf)))) 8000))
   True)

; One shared projection applies each policy and resolves conflicting labels safely.
(= (test-composition-policy $classes $level)
   (progn
     (change-state! &cfv2-relational-space
        (collapse (let $class (superpose $classes)
           (Relation (FrameID-1 FrameB) (FrameID-2 FrameA) (Class $class) (Reason "related") (Confidence 0.9)))))
     (change-state! &composition-policy-content (repr (cfv2-related-frames-for-prompt)))
     (test (size-atom (cfv2-related-frames-for-prompt)) (if (== $level Excluded) 0 1))
     (if (== $level Excluded) ()
        (test (contains-text (get-state &composition-policy-content) (repr (context-level $level))) True))
     (test (contains-text (get-state &composition-policy-content) "prepare plan") (== $level Working))
     (test (contains-text (get-state &composition-policy-content) "beginner audience") (== $level Working))
     (test (contains-text (get-state &composition-policy-content) "existing onboarding plan")
           (or (== $level Working) (== $level Dependency)))
     (test (contains-text (get-state &composition-policy-content) "day two exercises") (not (== $level Excluded)))
     (test (contains-text (get-state &composition-policy-content) "earlier planning decisions")
           (and (not (== $level Excluded)) (not (is-member Supersedes $classes))))))

!(collapse (let ($classes $level)
   (superpose (((ContinuationOf) Working) ((FollowUp) Working) ((DuplicateOf) Working)
      ((SubgoalOf) Working) ((ParentOf) Working)
      ((DependsOn) Dependency) ((Blocks) Dependency)
      ((SameProject) Reference) ((SameFailureCluster) Reference) ((Supersedes) Reference)
      ((RelatedButSeparate) Excluded) ((Unrelated) Excluded) ((UnknownClass) Excluded)
      ((ContinuationOf Supersedes) Reference) ((FollowUp RelatedButSeparate) Excluded)
      ((FollowUp Unrelated) Excluded) ((FollowUp UnknownClass) Excluded)
      ((FollowUp DependsOn SameProject) Working) ((DependsOn SameProject) Dependency)))
   (test-composition-policy $classes $level)))
!(test (== (cfv2ActiveFrameSpace) (get-state &composition-active-before)) True)
!(test (== (cfv2CompletedFrameSpace) (get-state &composition-completed-before)) True)
!(test (== (get-state FrameA) (get-state &composition-goals-before)) True)
!(test (cfv2-root-current-frame-id) FrameB)

; A larger graph cannot expand the prompt beyond five distinct direct frames.
!(collapse (let $id (superpose (FrameC FrameD FrameE FrameF FrameG))
   (change-state! $id ())))
!(change-state! &cfv2-relational-space
   (collapse (let $id (superpose (FrameA FrameC FrameD FrameE FrameF FrameG))
      (Relation (FrameID-1 FrameB) (FrameID-2 $id) (Class FollowUp) (Reason "extend") (Confidence 0.9)))))
!(change-state! &cfv2-active-framespace
   (collapse (let $id (superpose (FrameA FrameC FrameD FrameE FrameF FrameG))
      (test-composition-frame $id Active))))
!(test (size-atom (cfv2-related-frames-for-prompt)) 5)
!(change-state! &cfv2-relational-space ())
!(test (cfv2-related-frames-for-prompt) ())
!(change-state! &cfv2-current-frame-id ())
!(test (cfv2-related-frames-for-prompt) ())

; Completion snapshots precede AfterTools; composition must read the final batch.
(= (remember $content) REMEMBER-SUCCESS)
(= (test-completed-frame-composition $complete)
   (progn
     (cfv2-init-context-frames)
     (change-state! &cfv2-root-mode Fast)
     (change-state! &cfv2-active-framespace
        ((test-composition-frame FrameA Active) (test-composition-frame FrameB Active)))
     (cfv2-load-frame FrameA)
     ($complete "done")
     (cfv2-record-command-batch-for-frame FrameA
        ((send "final three-day Docker plan") ($complete "done")) (SUCCESS))
     (cfv2-set-frame-prune-record FrameA "preserved decision from pruned history"
        "2026-11-12 00:00:00" "2026-11-12 00:00:00" 1)
     (test (cfv2-get-frame-events FrameB ()) ())
     (cfv2-load-frame FrameB)
     (change-state! &cfv2-current-results ("latest live result"))
     (test (contains-text (repr (cfv2-classification-frames)) "(status Completed)") True)
     (let ($saved $completed $hot) (cfv2-classification-frames)
        (test (contains-text (repr $hot) "latest live result") True))
     (test (contains-text (repr (cfv2ActiveFrameSpace)) "latest live result") False)
     (change-state! &cfv2-relational-space
        ((Relation (FrameID-1 FrameB) (FrameID-2 FrameA)
           (Class FollowUp) (Reason "extend the delivered plan") (Confidence 0.9))))
     (change-state! &composition-completed-before (cfv2CompletedFrameSpace))
     (test (contains-text (repr (get-state &composition-completed-before)) "final three-day Docker plan") False)
     (test (contains-text (repr (cfv2-context-projection)) "final three-day Docker plan") True)
     (test (contains-text (repr (cfv2-context-projection)) "preserved decision from pruned history") True)
     (test (contains-text (repr (cfv2-related-frames-for-prompt)) "(status Completed)") True)
     (test (contains-text (repr (cfv2-related-frame-content
        (cfv2-get-frame FrameA &cfv2-completed-framespace) (Supersedes))) "final three-day Docker plan") False)
     (test (== (cfv2CompletedFrameSpace) (get-state &composition-completed-before)) True)
     (test (== (get-state FrameA) (get-state &composition-goals-before)) True)
     (test (cfv2-root-current-frame-id) FrameB)))

!(collapse (let $complete
   (superpose (cfv2-complete-current-frame-to-stm cfv2-complete-current-frame-to-ltm))
   (test-completed-frame-composition $complete)))
