(= (getFrameSkillsCompact) (getSkills))

;; TODO: Frame composition is now based on semantic search and LLM classification,
;;       for the future development it should avoid LLM classification and just
;;       use symbolic reasoning, of course there is an issue of not enough dataset,
;;       try to explore factor graph based reasoning of PLN/NAL it seems like a good approach

(= (cfv2ModeFast) Fast)
(= (cfv2ModeSlow) Slow)

(= (cfv2StatusActive) Active)
(= (cfv2StatusFocused) Focused)
(= (cfv2StatusSuspended) Suspended)
(= (cfv2StatusBlocked) Blocked)
(= (cfv2StatusCompleted) Completed)
(= (cfv2StatusFailed) Failed)
(= (cfv2StatusArchived) Archived)

(= (cfv2GoalStatusProposed) Proposed)
(= (cfv2GoalStatusActive) Active)
(= (cfv2GoalStatusBlocked) Blocked)
(= (cfv2GoalStatusSatisfied) Satisfied)
(= (cfv2GoalStatusFailed) Failed)
(= (cfv2GoalStatusSuspended) Suspended)
(= (cfv2GoalStatusRejected) Rejected)

(= (cfv2SourceUser) UserDirective)
(= (cfv2SourceAgent) AgentDirective)

(= (cfv2SpaceActive) Active)
(= (cfv2SpaceCompleted) Completed)

(= (cfv2PayloadLimit) 900)
(= (cfv2HistorySummaryLimit) 2400)
(= (cfv2PrunedHistorySummaryLimit) 1200)
(= (cfv2LastResultsLimit) 1200)
(= (maxFrameHistoryEvents) (empty))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Python helper wrappers
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(= (cfv2-now)
   (swrite (py-call (frame_helpers.cfv2_now))))

(= (cfv2-make-id $prefix)
   (py-call (helper.make_id (repr $prefix))))

(= (cfv2-compact-plain $value)
   (py-call
      (frame_helpers.compact_plain
         (repr $value)
         (cfv2LastResultsLimit))))

(= (cfv2-compact-limited $value $limit)
   (py-call
      (frame_helpers.compact_plain
         (repr $value)
         $limit)))

(= (cfv2-history-payload $value)
   (py-call
      (frame_helpers.cfv2_history_payload
         (repr $value)
         (cfv2PayloadLimit))))

(= (cfv2-compact-history $events)
   (py-call
      (frame_helpers.cfv2_compact_history
         (repr $events)
         (cfv2HistorySummaryLimit))))

(= (cfv2-compact-frame-history $events $pruningSummary)
   (py-call
      (frame_helpers.cfv2_compact_frame_history
         (repr $events)
         (repr $pruningSummary)
         (cfv2HistorySummaryLimit))))

(= (cfv2-pruned-event-timestamp $events $position)
   (swrite
      (py-call
         (frame_helpers.cfv2_pruned_event_timestamp
            (repr $events)
            (repr $position)))))

(= (cfv2-update-pruning-summary $previous $pruned $from $to $count)
   (py-call
      (frame_helpers.cfv2_update_pruning_summary
         (repr $previous)
         (repr $pruned)
         (repr $from)
         (repr $to)
         $count
         (cfv2PrunedHistorySummaryLimit))))

(= (cfv2-pruned-audit-entry $event)
   (py-call (frame_helpers.cfv2_pruned_audit_entry (repr $event))))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Defaults
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(= (cfv2-default-method)
   (CertifiedMethod
      (status None)
      (description "")
      (parameters ())
      (evaluation-protocol ())
      (certificate-hash "")))

(= (cfv2-default-budget)
   (ResourceBudget
      (max-output-tokens (maxOutputToken))
      (max-command-lines 5)
      (wake-interval (wakeupInterval))
      (status Open)))

(= (cfv2-default-constraints)
   ((Constraint FrameIsAuthority
      "The current frame is the authoritative task state for the focused work item.")
    (Constraint RootIsPointerOnly
      "RootFrame stores only IDs, space names, global budget and global constraints; full frames live in spaces.")
    (Constraint NoRawThoughtPrompting
      "Do not rely on raw transcript history as working state.")
    (Constraint SkillCommandsOnly
      "The agent may invoke only commands listed in the skill set.")
    (Constraint AuditViaHistory
      "Exact chronological audit is available through history.metta, pin, episodes and runtime logs; frames store compact history summaries.")
    (Constraint NoUnjustifiedAutonomousSideEffects
      "Autonomous actions must serve an active current frame and respect budget.")))

(= (cfv2-default-modules)
   (NONE FOR NOW
      ; (Entry send
      ; (ModuleProfile (kind Skill) (capabilities (RespondToUser)) (rating 1.0)))
      ))

(= (cfv2-prompt-modules)
   ((Entry skill-set
      (ModuleProfile
         (kind SkillSet)
         (capabilities
            (send remember query episodes pin read-file write-file append-file websearch tavily-search technical-analysis
               metta new-frame new-autonomous-frame switch-frame switch-mode show-root-frame show-current-frame show-frame-index
               show-active-framespace show-completed-framespace cfv2-get-relation complete-goals-stm complete-goals-ltm clear-frame-junk))
         (rating 1.0)))))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Constructors
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
(= (cfv2ActiveFrameSpace)
    (get-state &cfv2-active-framespace))
(= (cfv2CompletedFrameSpace)
    (get-state &cfv2-completed-framespace))
(= (cfv2FrameIndexSpace)
    (get-state &cfv2-frame-indexspace))

;; TODO: rename function to -> cfv2-root-frame
;; - change the current-frame-id getter to this function cfv2-root-current-frame-id
;; Update: both comments are addressed
(= (cfv2-root-frame)
   (RootFrame
      (id (get-state &cfv2-root-id))
      (current-frame-id (cfv2-root-current-frame-id))
      (last-admitted-frame-id (get-state &cfv2-last-admitted-frame-id))
      (active-framespace &cfv2-active-framespace)
      (completed-framespace &cfv2-completed-framespace)
      (frame-indexspace &cfv2-frame-indexspace)
      (relational-space &cfv2-relational-space)
      (mode (get-state &cfv2-root-mode))
      (global-budget (get-state &cfv2-global-budget))
      (global-constraints (get-state &cfv2-global-constraints))))

(= (cfv2-make-goal $goalID $frameID $subFrameID $description $source $priority $criteria)
   (Goal
      (goalID $goalID)
      (frameID $frameID)
      (sub-frameID $subFrameID)
      (description $description)
      (status Active)
      (source $source)
      (priority $priority)
      (dependencies ())
      (success-criteria $criteria)
      (created-at (cfv2-now))
      (completed-at ())
      (completion-summary ())))

(= (cfv2-make-deliverable $description)
   (Deliverable
      (id (cfv2-make-id Deliverable))
      (description $description)
      (status Pending)))


;; TODO: change the current-frame-id getter to this function cfv2-root-current-frame-id.
;;       Also change how current frame is set.
(= (cfv2-current-frame)
   (if (== (cfv2-root-current-frame-id) ())
       NO-CURRENT-FRAME-SET
      ; (cfv2-get-frame (cfv2-root-current-frame-id) Active)
      (Frame
        (frameID (cfv2-root-current-frame-id))
        (parent-frameID (get-state &cfv2-current-parent-frame-id))
        (source (get-state &cfv2-current-source))
        (priority (get-state &cfv2-current-priority))
        (goal-namespace (get-state &cfv2-current-goal-namespace))
        (status (get-state &cfv2-current-status))
        (frame-mode (get-state &cfv2-current-frame-mode))
        (hypotheses (get-state &cfv2-current-hypotheses))
        (method (get-state &cfv2-current-method))
        (history-summary (get-state &cfv2-current-history-summary))
        (modules (get-state &cfv2-current-modules))
        (budget (get-state &cfv2-current-budget))
        (constraints (get-state &cfv2-current-constraints))
        (deliverables (get-state &cfv2-current-deliverables))
        (sub-frame-namespace (get-state &cfv2-current-sub-frame-namespace))
        (results (get-state &cfv2-current-results))
        (created-at (get-state &cfv2-current-created-at))
        (updated-at (get-state &cfv2-current-updated-at))
        (completed-timestamp (get-state &cfv2-current-completed-timestamp))
        (completed-summary (get-state &cfv2-current-completed-summary)))
          ))

(= (frame-for-prompt)
   (if (== (cfv2-root-current-frame-id) ()) NO-CURRENT-FRAME-SET
      (let* (((Frame $frameID $parentFrameID $source $priority $goalNamespace $status $frameMode $hypotheses $method $historySummary
                     $modules $budget $constraints $deliverables $subFrameNamespace $results $createdAt $updatedAt $completedTimestamp $completedSummary)
            (cfv2-current-frame))
         ; ($_ (log DEBUG "context" ("Current frame for prompt: " $frameID))) ;; enable for debug
         )

         (Frame $frameID $parentFrameID $source $priority $goalNamespace
               $status $frameMode $historySummary $deliverables $subFrameNamespace
               $results $createdAt $updatedAt $completedTimestamp $completedSummary))))

;; TODO: change the current-frame-id getter to this function cfv2-root-current-frame-id.
;; Update: the current frame ID is now taken from the root's current frame ID.
(= (cfv2-make-frame-ref-from-current $frameID $space)
    (let $currentFrameID (if (== () $frameID) (cfv2-root-current-frame-id) $frameID)
        (let*
            (
               ; ($_ (log DEBUG "context" $frame))
               ((Frame $frameID' $parentFrameID $source $priority $goalNamespace (status $statusValue) $frameMode $hypotheses $method (history-summary $historySummary)
                     $modules $budget $constraints $deliverables $subFrameNamespace $results $createdAt $updatedAt $completedTimestamp $completedSummary)
                  (cfv2-get-frame $currentFrameID $space))
               ; ($_ (log DEBUG "context" ("Creating frame reference for frameID: " $currentFrameID " in space: " $space)))
            )
            (FrameRef
                (frameID $currentFrameID) $parentFrameID (space (if (== $space &cfv2-completed-framespace) Completed Active)) $source
                $priority (status $statusValue) $frameMode
                (summary (cfv2-compact-limited $historySummary (cfv2PayloadLimit)))
                $createdAt $updatedAt $completedTimestamp))))


(= (cfv2-context-projection)
   (ContextProjection
      (RootFrame (cfv2-root-frame))
      (CurrentFrame (frame-for-prompt))
      (RelatedFrames (cfv2-related-frames-for-prompt))
   ))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Initialization
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(= (cfv2-clear-current-frame-cache)
   (progn
      (change-state! &cfv2-current-frame-id ())
      (change-state! &cfv2-current-frame-id ())
      (change-state! &cfv2-current-parent-frame-id ())
      (change-state! &cfv2-current-source ())
      (change-state! &cfv2-current-priority 0.0)
      (change-state! &cfv2-current-goal-namespace ())
      (change-state! &cfv2-current-status ())
      (change-state! &cfv2-current-frame-mode ())
      (change-state! &cfv2-current-hypotheses ())
      (change-state! &cfv2-current-method (cfv2-default-method))
      (change-state! &cfv2-current-history-summary "")
      (change-state! &cfv2-current-modules (cfv2-default-modules)) ;; TODO: just call compact skill from skill.metta
      (change-state! &cfv2-current-budget (cfv2-default-budget))
      (change-state! &cfv2-current-constraints (cfv2-default-constraints))
      (change-state! &cfv2-current-deliverables ())
      (change-state! &cfv2-current-sub-frame-namespace ())
      (change-state! &cfv2-current-results ())
      (change-state! &cfv2-current-created-at ())
      (change-state! &cfv2-current-updated-at ())
      (change-state! &cfv2-current-completed-timestamp ())
      (change-state! &cfv2-current-completed-summary ())
      ; (change-state! &cfv2-current-goal ())
      CURRENT-FRAME-CACHE-CLEARED))

(= (cfv2-init-context-frames)
   (progn
      ;; Root state.
      (cfv2-clear-current-frame-cache)

      (change-state! &cfv2-root-id (cfv2-make-id RootFrame))
      (change-state! &cfv2-root-mode Slow)
      (change-state! &cfv2-global-budget (cfv2-default-budget))
      (change-state! &cfv2-global-constraints (cfv2-default-constraints))
      (change-state! &cfv2-last-admitted-frame-id ())
      (change-state! &cfv2-current-frame-id ())

      ;; List-backed external spaces. These are intentionally not in RootFrame.
      (change-state! &cfv2-active-framespace ())
      (change-state! &cfv2-completed-framespace ())
      (change-state! &cfv2-frame-indexspace ())
      (change-state! &cfv2-goalspace ())
      (change-state! &cfv2-subframespace ())
      (change-state! &cfv2-frame-event-space ())
      (change-state! &cfv2-frame-prune-space ())
      (configure maxFrameHistoryEvents 100)

      ;; Relational states used in frame composition
      (change-state! &cfv2-relational-space ())

      ;; Hot focused frame cache.
      CONTEXT-FRAMES-V2-INITIALIZED))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Space append/index helpers
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; TODO: The function calls get-state regardless of the space being empty.
;;       - Check the rest Space Append functions for the same issue.
(= (cfv2-add-active-frame $frame)
   (let $currentSpace (if (== (get-state &cfv2-active-framespace) ())
      ((get-state &cfv2-active-framespace)) (get-state &cfv2-active-framespace))
      (change-state! &cfv2-active-framespace
         (append $currentSpace ($frame)))))

(= (cfv2-add-completed-frame $frame)
   (let $currentSpace (if (== (get-state &cfv2-completed-framespace) ())
      ((get-state &cfv2-completed-framespace)) (get-state &cfv2-completed-framespace))
      (change-state! &cfv2-completed-framespace
         (append $currentSpace ($frame)))))

(= (cfv2-add-frame-ref $ref)
   (let $currentSpace (if (== (get-state &cfv2-frame-indexspace) ())
      ((get-state &cfv2-frame-indexspace)) (get-state &cfv2-frame-indexspace))
      (change-state! &cfv2-frame-indexspace
         (append $currentSpace ($ref)))))

(= (cfv2-add-goal $goal $goalspace)
   (let $currentSpace (if (== (get-state $goalspace) ())
      ((get-state $goalspace)) (get-state $goalspace))
      (change-state! $goalspace
         (append $currentSpace ($goal)))))

(= (cfv2-add-sub-frame $subFrame $subframespace)
   (let $currentSpace (if (== (get-state $subframespace) ())
      ((get-state $subframespace)) (get-state $subframespace))
      (change-state! $subframespace
         (append $currentSpace ($subFrame)))))

(= (cfv2-add-and-remove $frameID $newFrame $space)
   (let $newSpaceContent (filter-atom (get-state $space) $frame
        (== (cfv2-check-frame-id $frame $frameID) False))
        (change-state! $space (append $newSpaceContent ($newFrame)))))

;; TODO: change the way current frame is snapshotted.
;; Update: The snapshot function has changed to take a frame as an argument. The current frame is now snapshotted by passing a frame.
(= (cfv2-snapshot-current-frame $space $frame)
       (if (== $space Completed)
           (cfv2-add-completed-frame $frame)
           (cfv2-add-active-frame $frame)))

(= (cfv2-index-current-frame $frameID $space)
   ; (if (== (cfv2-root-current-frame-id) ())
   ;     NO-CURRENT-FRAME-TO-INDEX
   (let $namespace (if (== $space Completed) &cfv2-completed-framespace &cfv2-active-framespace)
         (cfv2-add-frame-ref (cfv2-make-frame-ref-from-current $frameID $namespace))))
      ;  )

(= (cfv2-switch-mode)
   (change-state! &cfv2-root-mode
      (if (== (get-state &cfv2-root-mode) Fast) Slow Fast)))
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Root helpers
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
(= (cfv2-root-mode)
   (get-state &cfv2-root-mode))

(= (cfv2-set-root-mode $mode)
   (if (or (== $mode Fast) (== $mode Slow))
       (progn (change-state! &cfv2-root-mode $mode) (cfv2-root-frame))
       (InvalidRootMode $mode)))

(= (cfv2-root-current-frame-id)
   (get-state &cfv2-current-frame-id))

(= (cfv2-root-set-current-frame-id $frameID)
   (change-state! &cfv2-current-frame-id $frameID))


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Current frame mutation helpers
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(= (cfv2-touch-current-frame)
   (change-state! &cfv2-current-updated-at (cfv2-now)))

(= (cfv2-history-event-type $event)
   (case $event (
      (UserDirective (HistoryEventType Directive UserDirective))
      (UserMessageForCurrentFrame (HistoryEventType Directive UserDirective))
      (AgentDirective (HistoryEventType Directive AgentDirective))
      (CommandBatch (HistoryEventType Execution CommandBatch))
      (ResultAdded (HistoryEventType Observation ResultAdded))
      (HypothesisAdded (HistoryEventType StateChange HypothesisAdded))
      (CertifiedMethodUpdated (HistoryEventType StateChange MethodCertified))
      (DeliverableAdded (HistoryEventType StateChange DeliverableAdded))
      (ConstraintAdded (HistoryEventType StateChange ConstraintAdded))
      (SubFrameCompleted (HistoryEventType Lifecycle FrameCompleted))
      (FrameCompleted (HistoryEventType Lifecycle FrameCompleted))
      (FrameJunkCleared (HistoryEventType Maintenance FrameJunkCleared))
      ($_ (HistoryEventType Unclassified $event))
   )))

;; Events share one initialized state and are selected by frame ID and category.
(= (cfv2-get-frame-events $frameID $category)
   (filter-atom (get-state &cfv2-frame-event-space) $event
      (cfv2-check-frame-event $event $frameID $category)))

(= (cfv2-check-frame-event
      (FrameEvent (frameID $eventFrameID) (category $eventCategory) (kind $kind)
         (payload $payload) (timestamp $timestamp))
      $frameID $category)
   (and
      (== $eventFrameID $frameID)
      (or (== $category ())
          (== $eventCategory $category))))

(= (cfv2-event-timestamp
      (FrameEvent (frameID $frameID) (category $category) (kind $kind)
         (payload $payload) (timestamp $timestamp)))
   $timestamp)

(= (cfv2-add-frame-event $frameID (HistoryEventType $category $kind) $payload)
   (let* (($event (FrameEvent
                    (frameID $frameID)
                    (category $category)
                    (kind $kind)
                    (payload (cfv2-history-payload $payload))
                    (timestamp (cfv2-now))))
          ($events (append (get-state &cfv2-frame-event-space) ($event))))
      (progn
         (change-state! &cfv2-frame-event-space $events)
         (cfv2-prune-frame-events $frameID))))

(= (cfv2-list-length ()) 0)
(= (cfv2-list-length (cons $_ $tail))
   (+ 1 (cfv2-list-length $tail)))

(= (cfv2-prune-frame-events $frameID)
   (let* (($frameEvents (cfv2-get-frame-events $frameID ()))
          ($eventCount (cfv2-list-length $frameEvents))
          ($limit (max 1 (maxFrameHistoryEvents)))
          ($removeCount (max 0 (- $eventCount $limit))))
      (if (== $removeCount 0)
          NO-PRUNING-NEEDED
          (let* (($pruned (take $removeCount $frameEvents))
                 ($from (cfv2-pruned-event-timestamp $pruned First))
                 ($to (cfv2-pruned-event-timestamp $pruned Last))
                 ($oldRecord (cfv2-get-frame-prune-record $frameID))
                 ($oldSummary (cfv2-prune-summary $oldRecord))
                 ($oldFrom (cfv2-prune-from $oldRecord))
                 ($oldCount (cfv2-prune-count $oldRecord))
                 ($rangeFrom (if (== $oldFrom "") $from $oldFrom))
                 ($rangeTo $to)
                 ($totalCount (+ $oldCount $removeCount))
                 ($summary (cfv2-update-pruning-summary
                              $oldSummary $pruned $rangeFrom $rangeTo $totalCount))
                 ($remaining (cfv2-remove-oldest-frame-events
                               (get-state &cfv2-frame-event-space)
                               $frameID $removeCount)))
             (progn
                (cfv2-archive-pruned-events $pruned)
                (change-state! &cfv2-frame-event-space $remaining)
                (cfv2-set-frame-prune-record
                   $frameID $summary $rangeFrom $rangeTo $totalCount)
                (if (== (get-state &cfv2-current-frame-id) $frameID)
                    (cfv2-refresh-current-history-summary)
                    ())
                HISTORY-PRUNED)))))

(= (cfv2-remove-oldest-frame-events () $frameID $removeCount) ())
(= (cfv2-remove-oldest-frame-events (cons $event $tail) $frameID $removeCount)
   (if (and (> $removeCount 0)
            (cfv2-check-frame-event $event $frameID ()))
       (cfv2-remove-oldest-frame-events $tail $frameID (- $removeCount 1))
       (cons $event (cfv2-remove-oldest-frame-events $tail $frameID $removeCount))))

(= (cfv2-archive-pruned-events ()) ARCHIVE-COMPLETE)
(= (cfv2-archive-pruned-events (cons $event $tail))
   (progn
      (append-file-raw
         (joinPath ((projectRootDirectory) "memory" "history.metta"))
         (cfv2-pruned-audit-entry $event))
      (cfv2-archive-pruned-events $tail)))

(= (cfv2-get-frame-prune-record $frameID)
   (cfv2-get-frame-prune-record-from
      (filter-atom (get-state &cfv2-frame-prune-space) $record
         (cfv2-check-prune-record $record $frameID))
      $frameID))
(= (cfv2-get-frame-prune-record-from
      (cons (FramePruneSummary $frameID $summary $from $to $count) $_) $frameID)
   (FramePruneSummary $frameID $summary $from $to $count))
(= (cfv2-get-frame-prune-record-from () $frameID)
   (FramePruneSummary $frameID "" "" "" 0))
(= (cfv2-check-prune-record
      (FramePruneSummary $recordFrameID $summary $from $to $count) $frameID)
   (== $recordFrameID $frameID))
(= (cfv2-prune-summary (FramePruneSummary $frameID $summary $from $to $count)) $summary)
(= (cfv2-prune-from (FramePruneSummary $frameID $summary $from $to $count)) $from)
(= (cfv2-prune-count (FramePruneSummary $frameID $summary $from $to $count)) $count)

(= (cfv2-set-frame-prune-record $frameID $summary $from $to $count)
   (let $records (filter-atom (get-state &cfv2-frame-prune-space) $record
                     (not (cfv2-check-prune-record $record $frameID)))
      (change-state! &cfv2-frame-prune-space
         (append $records ((FramePruneSummary $frameID $summary $from $to $count))))))

(= (cfv2-refresh-current-history-summary)
   (change-state! &cfv2-current-history-summary
      (cfv2-compact-frame-history
         (cfv2-get-frame-events (get-state &cfv2-current-frame-id) ())
         (cfv2-prune-summary
            (cfv2-get-frame-prune-record (get-state &cfv2-current-frame-id))))))

(= (cfv2-update-current-history-summary $kind $summary)
   (let* (($frameID (get-state &cfv2-current-frame-id))
          ($eventType (cfv2-history-event-type $kind)))
      (if (== $frameID ())
          NO-CURRENT-FRAME-FOR-HISTORY
          (progn
             (cfv2-add-frame-event $frameID $eventType $summary)
             (cfv2-refresh-current-history-summary)
             HISTORY-EVENT-RECORDED))))

;; TODO: The snapshot function has changed to take a frame as an argument.
(= (cfv2-record-frame-note $kind $payload)
   (if (== (get-state &cfv2-current-frame-id) ())
       NO-CURRENT-FRAME-FOR-COMMAND-BATCH
       (progn
          (cfv2-update-current-history-summary $kind $payload)
          (cfv2-touch-current-frame)
          (FRAME-NOTE-RECORDED))))

(= (cfv2-record-command-batch $commands $results)
   (cfv2-record-command-batch-for-frame
      (get-state &cfv2-current-frame-id) $commands $results))

(= (cfv2-record-command-batch-for-frame $frameID $commands $results)
   (if (== $frameID ())
       NO-CURRENT-FRAME-FOR-COMMAND-BATCH
      (let $resultsSummary (append $commands $results)
         (progn
            (cfv2-add-frame-event $frameID
               (cfv2-history-event-type CommandBatch) $resultsSummary)
            (if (== (get-state &cfv2-current-frame-id) $frameID)
                (progn
                   (cfv2-refresh-current-history-summary)
                   (cfv2-touch-current-frame)
                   (HISTORY-SUMMARY-UPDATED))
                HISTORY-EVENT-RECORDED)))))

(= (cfv2-add-hypothesis $id $hypothesis)
   (progn
      (change-state! &cfv2-current-hypotheses
         (append (get-state &cfv2-current-hypotheses)
            ((Entry $id $hypothesis))))
      (cfv2-record-frame-note HypothesisAdded (Entry $id $hypothesis))))

;; TODO: Review required after full integration, On Entry $variant $metrics.
(= (cfv2-add-result $variant $metrics)
   (progn
      (change-state! &cfv2-current-results
         (append (get-state &cfv2-current-results)
            ((Entry $variant $metrics))))
      (cfv2-record-frame-note ResultAdded (Entry $variant $metrics))))

(= (cfv2-set-certified-method $description $parameters $evalProtocol $hash)
   (progn
      (change-state! &cfv2-current-method
         (CertifiedMethod
            (status Certified)
            (description $description)
            (parameters $parameters)
            (evaluation-protocol $evalProtocol)
            (certificate-hash $hash)))
      (cfv2-record-frame-note CertifiedMethodUpdated (get-state &cfv2-current-method))))


(= (cfv2-add-deliverable $description)
   (progn
      ; (log DEBUG "context" (get-state &cfv2-current-deliverables))
      (change-state! &cfv2-current-deliverables
         (append
            (get-state &cfv2-current-deliverables)
            ((cfv2-make-deliverable $description))))
      ; (log DEBUG "context" "Changed current deliverables state")
      (cfv2-record-frame-note DeliverableAdded $description)
      ))

(= (cfv2-add-constraint $constraint)
   (progn
      (change-state! &cfv2-current-constraints
         (append (get-state &cfv2-current-constraints)
            ($constraint)))
      (cfv2-record-frame-note ConstraintAdded $constraint)))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Frame creation and user-message ingestion
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; TODO: change the default method, modules, constraints, budget, etc; they are bloating the frame.
(= (cfv2-create-frame $source $description $priority $mode)
   (let* (($frameID (cfv2-make-id Frame))
          ($goalSpaceID (cfv2-make-id &GoalSpace))
          ($subFrameSpaceID (cfv2-make-id &SubFrameSpace))
          ($now (cfv2-now))
          ($_ (cfv2-add-frame-event $frameID (cfv2-history-event-type $source) $description))
          ($historySummary
             (cfv2-compact-frame-history
                (cfv2-get-frame-events $frameID ())
                (cfv2-prune-summary (cfv2-get-frame-prune-record $frameID))))
          ($deliverables $description)
          ($subframe (cfv2-create-sub-frame $frameID $subFrameSpaceID $goalSpaceID $description $source $priority $deliverables))
          ($compFrame (Frame (frameID $frameID) (parent-frameID ()) (source $source) (priority $priority) (status Active) (frame-mode $mode) (deliverables ($deliverables)) (results ())))
          ($relation (cfv2-compose-relations $frameID $compFrame))
          ($_ (change-state! &cfv2-relational-space (append (get-state &cfv2-relational-space) $relation)))
          ($frame (Frame
             (frameID $frameID)
             (parent-frameID ())
             (source $source)
             (priority $priority) ;; For future their should be heuristic to determine the priority of a frame based on the priority of its goal.
             (goal-namespace $goalSpaceID)
             (status Active)
             (frame-mode $mode)
             (hypotheses ())
             (method (cfv2-default-method))
             (history-summary $historySummary)
             (modules (getFrameSkillsCompact))
             (budget (cfv2-default-budget))
             (constraints ())
             (deliverables ($deliverables))
             (sub-frame-namespace $subFrameSpaceID)
             (results ())
             (created-at $now)
             (updated-at $now)
             (completed-timestamp ())
             (completed-summary ())
             ))
         )

      (progn
         (cfv2-snapshot-current-frame Active $frame)
         ; (log DEBUG "context" (CREATING-FRAME $frameID FROM $source WITH-MODE $mode))
         (cfv2-index-current-frame $frameID Active)
         ; (log DEBUG "context" (CREATING-FRAME $frameID FROM $source WITH-MODE $mode))
         (change-state! &cfv2-last-admitted-frame-id $frameID)
         (FRAME-CREATED-AND-STORED-IN-ACTIVE-FRAME-SPACE)

         (if (and (== $source UserDirective) (== (cfv2-root-mode) Slow))
            (progn (cfv2-switch-mode) (cfv2-load-frame $frameID) "NEW USER DIRECTED FRAME CREATED AND SWITCHED TO FAST MODE")
            _)

         (NewframeID $frameID)
         )))

;; User's message should always be on the Fast loop.
(= (cfv2-create-frame-from-user-message $msg)
   (cfv2-create-frame UserDirective $msg 1.0 Fast))

(= (cfv2-create-autonomous-frame $description $priority $mode)
   (cfv2-create-frame AgentDirective $description $priority $mode))

(= (cfv2-record-message-for-current-frame $msg)
   (if (== (get-state &cfv2-current-frame-id) ())
      NO-CURRENT-FRAME-FOR-COMMAND-BATCH
      (progn
         (cfv2-update-current-history-summary UserDirective $msg)
         (cfv2-touch-current-frame)
         MESSAGE-RECORDED-FOR-CURRENT-FRAME
         )))

;; TODO: There should be another function to update a frame with a user message if there is a frame already consisting
;;          ongoing frame for that specific user/module/sub-agents.
;; Update: Frame composition is implemented to address the above issue.
(= (cfv2-ingest-user-message $msg)
       (cfv2-create-frame-from-user-message $msg))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Frame Composition
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(= (cfv2-relation-types) (DuplicateOf ContinuationOf FollowUp SubgoalOf
                ParentOf DependsOn Blocks Supersedes SameProject
                SameFailureCluster RelatedButSeparate Unrelated))

(= (cfv2-classification-sketch
      (Frame $id $parent $source $priority $goals $status $mode $hypotheses $method
         $history $modules $budget $constraints $deliverables $subframes $results
         $createdAt $updatedAt $completedAt $summary))
   (Frame $id $parent $source $priority $status $mode $deliverables $results))

;; The hot cache comes last so its current values override the saved snapshot.
(= (cfv2-classification-frames)
   (let $frames
      (append (append (cfv2ActiveFrameSpace) (cfv2CompletedFrameSpace))
         (if (== (cfv2-root-current-frame-id) ()) () ((cfv2-current-frame))))
      (collapse (let $frame (superpose $frames)
         (cfv2-classification-sketch $frame)))))

;; TODO: Add a hyperparameter config since K is set to 5 by default.
(= (cfv2-compose-relations $queryFrameID $compFrame)
   (sread
      (py-call
         (frame_relation.cfv2_compose_frame_relations
            (repr ($compFrame))
            (repr $queryFrameID)
            (repr (cfv2-relation-types))
            (repr (embeddingprovider))
            5
            (repr (cfv2-classification-frames))))))

;; To be used as a tool for the agent.
(= (cfv2-get-relation $currentframeID)
   (let $frameIDAtom (if (== (get-metatype $currentframeID) Grounded)
                       (sread $currentframeID) $currentframeID)
      (filter-atom (get-state &cfv2-relational-space) (Relation (FrameID-1 $a) (FrameID-2 $b) (Class $class) (Reason $reason) (Confidence $conf))
         (or (== $frameIDAtom $a) (== $frameIDAtom $b)))))

(= (cfv2-relation-context-level $class)
   (case $class (
      (ContinuationOf Working) (FollowUp Working) (DuplicateOf Working)
      (SubgoalOf Working) (ParentOf Working)
      (DependsOn Dependency) (Blocks Dependency)
      (SameProject Reference) (SameFailureCluster Reference) (Supersedes Reference)
      ($_ Excluded))))

(= (cfv2-composition-context-level $classes)
   (let $levels (unique-atom (collapse (let $class (superpose $classes) (cfv2-relation-context-level $class))))
      (if (or (== $levels ()) (is-member Excluded $levels)) Excluded
         (if (is-member Supersedes $classes) Reference
            (if (is-member Working $levels) Working
               (if (is-member Dependency $levels) Dependency Reference))))))

;; Relations point from the current frame to the candidate; never walk the graph.
(= (cfv2-related-frames-for-prompt)
   (if (== (cfv2-root-current-frame-id) ())
       ()
       (let* (($relations (filter-atom (get-state &cfv2-relational-space)
                  (Relation (FrameID-1 $a) (FrameID-2 $b) (Class $class) (Reason $reason) (Confidence $confidence))
                  (and (== $a (cfv2-root-current-frame-id)) (not (== $a $b)))))
              ($ids (unique-atom (collapse
                  (let (Relation (FrameID-1 $a) (FrameID-2 $b) (Class $class) (Reason $reason) (Confidence $confidence))
                       (superpose $relations) $b)))))
          (take 5 (collapse
             (let* (($id (superpose $ids))
                    ($classes (unique-atom (collapse
                       (let (Relation (FrameID-1 $a) (FrameID-2 $b) (Class $class) (Reason $reason) (Confidence $confidence))
                            (superpose $relations)
                          (if (== $b $id) $class (empty))))))
                    ($frames (if (== (cfv2-composition-context-level $classes) Excluded)
                       ()
                       (filter-atom (append (cfv2ActiveFrameSpace) (cfv2CompletedFrameSpace))
                          $frame (cfv2-check-frame-id $frame $id)))))
                (if (== $frames ())
                    (empty)
                    (RelatedFrame
                       (relations $classes)
                       (cfv2-related-frame-content (car-atom $frames) $classes)))))))))

(= (cfv2-related-frame-content
      (Frame (frameID $id) $parentID (source $source) $priority
         (goal-namespace $goalSpace) (status $status) $mode $hypotheses $method
         (history-summary $history) $modules $budget (constraints $constraints)
         (deliverables $deliverables) $subFrameSpace (results $results)
         $createdAt $updatedAt $completedAt (completed-summary $summary)) $classes)
   (let* (($level (cfv2-composition-context-level $classes))
          ($events (cfv2-get-frame-events $id ())))
      (Frame
         (frameID $id)
         (source $source)
         (status $status)
         (context-level $level)
         (goals (if (== $level Working)
            (cfv2-compact-limited (get-state $goalSpace) (cfv2PayloadLimit)) ()))
         (constraints (if (== $level Working)
            (cfv2-compact-limited $constraints (cfv2PayloadLimit)) ()))
         (deliverables (if (== $level Reference) ()
            (cfv2-compact-limited $deliverables (cfv2PayloadLimit))))
         (results (cfv2-compact-plain $results))
         (completed-summary (cfv2-compact-limited $summary (cfv2PayloadLimit)))
         (history-summary (if (is-member Supersedes $classes) ()
            (if (== $events ())
                (cfv2-compact-limited $history (cfv2HistorySummaryLimit))
                (cfv2-compact-history $events)))))))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; SubFrame creation
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(= (cfv2-create-sub-frame $frameID $subFrameSpaceID $goalSpace $description $source $priority $deliverables)
       (let* (($subFrameID (cfv2-make-id SubFrame))
              ($goalID (cfv2-make-id Goal))
              ($goal (cfv2-make-goal $goalID $frameID $subFrameID
                        $description $source $priority $deliverables))
              ($subFrame
                 (SubFrame
                    (sub-frameID $subFrameID)
                    (frameID $frameID)
                    (priority $priority)
                    (status Active)
                    (goal $goal)
                    (deliverables $deliverables)
                    (dependencies ())
                    (created-at (cfv2-now))
                    (completed-at ())
                    (completion-summary ()))))
          (progn
            ; (log DEBUG "context" $goalspace)
            (change-state! $goalSpace ())
            (change-state! $subFrameSpaceID ())
            (cfv2-add-goal $goal $goalSpace)
            ; (log DEBUG "context" $goalSpace)
            (cfv2-add-sub-frame $subFrame $subFrameSpaceID)
            ; (log DEBUG "context" $subFrameSpaceID)
            $subFrame)))

(= (cfv2-complete-sub-frame $subFrameID $summary)
   (cfv2-record-frame-note SubFrameCompleted
      (SubFrameCompletion
         (sub-frameID $subFrameID)
         (summary $summary)
         (completed-at (cfv2-now)))))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Frame retrieval and switching
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;; Alternative for cfv2-load-frame-atom and cfv2-switch-frame
;; TODO: when switching frames, the current frame should be snapshotted and indexed before switching to the new frame.
;; Update: the current frame is now snapshoted and relational composition is done before switching to the new frame.
(= (cfv2-load-frame $currentframeID)
    (let* (
            ($frameIDAtom (if (== (get-metatype $currentframeID) Grounded) (sread $currentframeID) $currentframeID))
            ((Frame (frameID $frameID) (parent-frameID $parentID) (source $source)
                (priority $priority) (goal-namespace $goalSpace) (status $status)
                (frame-mode $mode) (hypotheses $hypotheses) (method $methods)
                (history-summary $historySummary) (modules $modules) (budget $budget)
                (constraints $constraint) (deliverables $deliverables)
                (sub-frame-namespace $subFrameSpaceID) (results $result)
                (created-at $createdAt) (updated-at $updatedAt) (completed-timestamp $completedTimestamp)
                (completed-summary $completedSummary))

               (cfv2-get-frame $frameIDAtom &cfv2-active-framespace))

            ($relation (collapse (cfv2-get-relation $frameIDAtom)))
            )

        (if (== $mode (cfv2-root-mode))
            (progn
               ;; Safe offloading frames back to active space when switching frames before they are completed.
               (if  (== () (get-state &cfv2-current-frame-id)) NEW-FRAME-SWITCHING (cfv2-add-and-remove (get-state &cfv2-current-frame-id) (cfv2-current-frame) &cfv2-active-framespace))

               (change-state! &cfv2-current-frame-id $frameIDAtom)
               (change-state! &cfv2-current-parent-frame-id $parentID)
               (change-state! &cfv2-current-source $source)
               (change-state! &cfv2-current-priority $priority)
               (change-state! &cfv2-current-goal-namespace $goalSpace)
               (change-state! &cfv2-current-status $status)
               (change-state! &cfv2-current-frame-mode $mode)
               (change-state! &cfv2-current-hypotheses $hypotheses)
               (change-state! &cfv2-current-method $methods)
               (change-state! &cfv2-current-history-summary $historySummary)
               (change-state! &cfv2-current-modules $modules)
               (change-state! &cfv2-current-budget $budget)
               (change-state! &cfv2-current-constraints $constraint)
               (change-state! &cfv2-current-deliverables $deliverables)
               (change-state! &cfv2-current-sub-frame-namespace $subFrameSpaceID)
               (change-state! &cfv2-current-results $result)
               (change-state! &cfv2-current-created-at $createdAt)
               (change-state! &cfv2-current-updated-at $updatedAt)
               (change-state! &cfv2-current-completed-timestamp $completedTimestamp)
               (change-state! &cfv2-current-completed-summary $completedSummary)
               (cfv2-refresh-current-history-summary)

               ((CurrentFrame (cfv2-current-frame))
                  (Relation (collapse $relation)))) ;; return the frame state after loading and its relation
            "FRAME MODE NOT ALLOWED FOR ROOT MODE, SWITCH TO A FRAME HAVING THE SAME MODE AND AS THE ROOT FRAME OR CONSIDER CHANGING THE ROOT MODE"
            )))

;; Build a Frame atom from the current-frame cache states.
(= (cfv2-current-cache-to-frame)
    (Frame
        (frameID (cfv2-root-current-frame-id))
        (parent-frameID (get-state &cfv2-current-parent-frame-id))
        (source (get-state &cfv2-current-source))
        (priority (get-state &cfv2-current-priority))
        (goal-namespace (get-state &cfv2-current-goal-namespace))
        (status (get-state &cfv2-current-status))
        (frame-mode (get-state &cfv2-current-frame-mode))
        (hypotheses (get-state &cfv2-current-hypotheses))
        (method (get-state &cfv2-current-method))
        (history-summary (get-state &cfv2-current-history-summary))
        (modules (get-state &cfv2-current-modules))
        (budget (get-state &cfv2-current-budget))
        (constraints (get-state &cfv2-current-constraints))
        (deliverables (get-state &cfv2-current-deliverables))
        (sub-frame-namespace (get-state &cfv2-current-sub-frame-namespace))
        (results (get-state &cfv2-current-results))
        (created-at (get-state &cfv2-current-created-at))
        (updated-at (get-state &cfv2-current-updated-at))
        (completed-timestamp (get-state &cfv2-current-completed-timestamp))
        (completed-summary (get-state &cfv2-current-completed-summary))))


;; TODO: make this generic for all use-case not only for frame ref
;; Update: The function is now generic for all use-cases, not only for frame ref.
;;         Also it now replaces the match implementation with state operation.
(= (cfv2-check-frame-id (Frame (frameID $currentID) $parentID $source $priority $goalNamespace $status $frameMode $hypotheses $method $historySummary
            $modules $budget $constraints $deliverables $subFrameNamespace $results $createdAt $updatedAt $completedTimestamp $completedSummary)
            $frameID)
    (if (== $currentID $frameID) True False))

(= (cfv2-check-frame-id (FrameRef (frameID $currentID) $parentFrameID $space
            $source $priority (status $refStatus) $frameMode
            $summary $createdAt $updatedAt $completedTimestamp)
            $frameID)
    (if (== $currentID $frameID) True False))

;; A more generic approach as an alternative for cfv2-frame-by-id and cfv2_latest_frame_by_id
(= (cfv2-get-frame $frameID $space)
    (car-atom (filter-atom (get-state $space) $frame
        (== (cfv2-check-frame-id $frame $frameID) True))))

;; Removes a frame or frame ref from a space by the given ID.
;; Works for both Frame and FrameRef atoms via cfv2-check-frame-id pattern dispatch.
(= (cfv2-remove-frame $frameID $frameSpace)
    (filter-atom (get-state $frameSpace) $frame
        (not (== (cfv2-check-frame-id $frame $frameID) True))))

(= (cfv2-select-next-frame)
   (let $nextID
      (py-call
         (frame_helpers.cfv2_select_next_frame_id
            (repr (cfv2-frame-refs-by-status Active))
            (repr (get-state &cfv2-root-mode))))
      (if (== $nextID NON)
          (progn
             (cfv2-clear-current-frame-cache)
             (NO-ACTIVE-FRAME-FOR-ROOT-MODE))
            (progn
               ; (log DEBUG "context" (SELECTING-NEXT-FRAME $nextID))
               (cfv2-load-frame $nextID))
          )))

(= (cfv2-check-ref-status (FrameRef $frameID $parentFrameID $space
                $source $priority (status $currentStatus) $frameMode
                $summary $createdAt $updatedAt $completedTimestamp)
                $status)
    (if (== $currentStatus $status) True False)
)

(= (cfv2-frame-refs-by-status $status)
   (if (== (cfv2FrameIndexSpace) ()) (FRAME-REF-EMPTY)
    (filter-atom (cfv2FrameIndexSpace) $frameRef
        (== (cfv2-check-ref-status $frameRef $status) True)))
)

(= (cfv2-completed-frame-refs-after $datePrefix)
   (sread
      (py-call
         (frame_helpers.cfv2_refs_completed_after
            (repr (get-state &cfv2-frame-indexspace))
            (repr $datePrefix)))))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Completion / STM / LTM
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(= (cfv2-completed-frame-memory $storage $summary)
   (py-str
      ("HyperClawFrameMemory "
       "kind=CompletedFrame "
       "storage=" $storage " "
       "time=" (cfv2-now) " "
       "frameID=" (get-state &cfv2-current-frame-id) " "
       "source=" (get-state &cfv2-current-source) " "
       "mode=" (get-state &cfv2-current-frame-mode) " "
       "priority=" (get-state &cfv2-current-priority) " "
       "deliverables=" (cfv2-compact-plain (get-state &cfv2-current-deliverables)) " "
       "method=" (cfv2-compact-plain (get-state &cfv2-current-method)) " "
       "results=" (cfv2-compact-plain (get-state &cfv2-current-results)) " "
       "history=" (cfv2-compact-plain (get-state &cfv2-current-history-summary)) " "
       "summary=" $summary)))

(= (cfv2-mark-current-frame-completed $summary)
   (progn
      (change-state! &cfv2-current-status Completed)
      (change-state! &cfv2-current-completed-timestamp (cfv2-now))
      (change-state! &cfv2-current-completed-summary $summary)
      (cfv2-update-current-history-summary FrameCompleted $summary)
      (cfv2-touch-current-frame)
      ; (cfv2-current-frame)
      ))

(= (cfv2-complete-current-frame-to-stm $summary)
   (if (== (get-state &cfv2-current-frame-id) ())
       (progn
         ;  (log WARNING "context" ("No current frame to complete; root current frame: " (cfv2-root-current-frame-id)))
          (NO-CURRENT-FRAME-TO-COMPLETE))
       (let $memory (cfv2-completed-frame-memory STM $summary)
          (progn
             (pin $memory)
             (cfv2-mark-current-frame-completed $summary)
             (change-state! &cfv2-active-framespace (cfv2-remove-frame (cfv2-root-current-frame-id) &cfv2-active-framespace))
             (change-state! &cfv2-frame-indexspace (cfv2-remove-frame (cfv2-root-current-frame-id) &cfv2-frame-indexspace))
             (cfv2-snapshot-current-frame Completed (cfv2-current-cache-to-frame))
             (cfv2-index-current-frame () Completed)
             (cfv2-clear-current-frame-cache)
             (cfv2-select-next-frame)
             FRAME-COMPLETED-STORED-STM))))

(= (cfv2-complete-current-frame-to-ltm $summary)
   (if (== (get-state &cfv2-current-frame-id) ())
       NO-CURRENT-FRAME-TO-COMPLETE
       (let $memory (cfv2-completed-frame-memory LTM $summary)
          (progn
             (remember $memory)
             (cfv2-mark-current-frame-completed $summary)
             (cfv2-snapshot-current-frame Completed (cfv2-current-cache-to-frame))
             (cfv2-index-current-frame () Completed)
             (change-state! &cfv2-active-framespace (cfv2-remove-frame (cfv2-root-current-frame-id) &cfv2-active-framespace))
             (change-state! &cfv2-frame-indexspace (cfv2-remove-frame (cfv2-root-current-frame-id) &cfv2-frame-indexspace))
             (cfv2-clear-current-frame-cache)
             (cfv2-select-next-frame)
             FRAME-COMPLETED-STORED-LTM))))

;; skipped cfv2-comapact-current-frame and cfv2-clear-current-frame-junk
;; Reason: the first is not needed, not for now, the second is redundant
;;TODO: evaluate thorologly of clear-frame-junk, is it really needed if we have a clear cache function that is called when there is no current frame or after completion and switching to the next frame?
(= (cfv2-clear-current-frame-junk $summary)
   (if (== (get-state &cfv2-current-frame-id) ())
       NO-CURRENT-FRAME-TO-CLEAR
       (progn
          (change-state! &cfv2-current-hypotheses ())
          (change-state! &cfv2-current-results ())
          (cfv2-update-current-history-summary FrameJunkCleared $summary)
          (cfv2-touch-current-frame)
         ;  (cfv2-snapshot-current-frame Active (cfv2-current-cache-to-frame))
         ;  (cfv2-index-current-frame Active)
          FRAME-JUNK-CLEARED)))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Maintenance
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

(= (cfv2-has-current-frame)
   (not (== (get-state &cfv2-current-frame-id) ())))

;; TODO: implement compact frame retrival
(= (cfv2-maintain-frame)
   (if (cfv2-has-current-frame)
       (progn
          (cfv2-touch-current-frame)
          (cfv2-current-frame))
       (cfv2-select-next-frame)))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; Backward compatibility with previous context.metta / loop.metta
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;


(= (initContextFrame)
   (cfv2-init-context-frames))

(= (currentRootFrame)
   (cfv2-root-frame))

(= (currentContextFrame)
   (cfv2-current-frame))

(= (contextFrameForPrompt)
   (swrite (cfv2-context-projection)))

;; TODO: this implementation needs to change see comment on cfv2-ingest-user-message
(= (ctx-ingest-user-message $msg)
   (cfv2-ingest-user-message $msg))

(= (ctx-record-command-batch $commands $results)
   (cfv2-record-command-batch $commands $results))

(= (ctx-record-command-batch-for-frame $frameID $commands $results)
   (cfv2-record-command-batch-for-frame $frameID $commands $results))

(= (ctx-maintain-frame)
   (cfv2-maintain-frame))

(= (ctx-has-active-goals)
   (cfv2-has-current-frame))

(= (ctx-compact-plain $value)
   (cfv2-compact-plain $value))

(= (compact-frame $summary)
   (progn
      (ctx-record-history FrameCompacted $summary)
      (change-state! &ctx-history-summary
         (last_chars
            (py-str
               ((get-state &ctx-history-summary)
                " | Compact: "
                $summary))
            (ctxHistorySummaryLimit)))
      (ctx-rebuild-history)
      (currentContextFrame)))
