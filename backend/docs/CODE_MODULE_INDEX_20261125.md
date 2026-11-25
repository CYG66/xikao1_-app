# 当前生产模块结构索引

该索引由全部生产Python源码AST生成，列出入口与依赖用于全读追踪。它不是逐行人工审阅完成证明，也不证明静态未引用函数无用。

## app/__init__.py

1行；SHA256 `9e59872332862ea4708e26d4d721a62f7418a1aadb5eeb8637a97c67452bf6aa`。

XLine Rover backend package.

顶层定义：无

## app/agent_attachments.py

89行；SHA256 `275c6665ff5433e02f4d8f13965e11125f22b4efebffe63e9af0d996fffb32c2`。

（无模块说明）

顶层定义：AgentAttachmentStore

## app/agent_evaluation.py

521行；SHA256 `d3435c82f3e217f2fb734f8c0d4e018f4db2c3639ea5e34d5e1651b06bc25e15`。

（无模块说明）

顶层定义：load_evaluation_corpus、_tool_names、_route_case、_reference_case、_answer_case、_cad_edit_case、_cad_case_result、_nested_value、_counterfactual_contract、_cad_counterfactual_case、_cad_followup_case、_cad_dxf_case、run_policy_evaluation

## app/agent_failure_policy.py

60行；SHA256 `015407adc66a8edcd4f9e02623850a965833067418d1e0e400eabae5028ef178`。

（无模块说明）

顶层定义：classify_agent_failure

## app/agent_http_service.py

1824行；SHA256 `018a2ce7c3e6b50e389c1132dbd7c317316a7efe1fd9784c9b6bf2a3f96f3df7`。

（无模块说明）

顶层定义：_agent_message_with_attachments、_enforce_requirement_confirmation、_candidate_acceptance_summary、_bind_and_filter_candidate_visibility、_routing_history、_resolve_cad_followup、_cad_navigation_action、_navigate_cad_candidate、_run_idempotency_key、_prepare_run_step、_generate_run_result、_finalize_run_result、agent_chat、agent_run_list、agent_run_detail、cancel_agent_run、resume_agent_run、_record_agent_run_result、_prepare_agent_chat_context、_execution_context_error、_agent_chat、_chat_stream_with_execution_context、agent_chat_stream、_agent_chat_stream_events

## app/agent_interruption_policy.py

111行；SHA256 `4686acb5fca2cf938775bcbb17b1b159a49e5feaaac59f8136804d695198eb37`。

Decide when an execution plan must interrupt the user.

顶层定义：InterruptionDecision、decide_step_interruption、apply_interruption_decision

## app/agent_plan_evaluation.py

58行；SHA256 `e5ffdc13f68036f5f2749f46407921244cc9c1e02fc8f159f33056f163790412`。

Evaluate persisted agent plan traces without invoking tools or models.

顶层定义：evaluate_plan_chain

## app/agent_plan_models.py

314行；SHA256 `13666b61b9c546595d1c86135a2df68d6cfbd6f7a95db17952314d8ae926488e`。

Strict contracts for goal-driven, verifiable agent execution plans.

顶层定义：_utc_now、AgentTargetRef、SuccessCriterion、GoalSpec、PlanStep、StepResult、ExecutionPlan、PlanEvent、PlanTransition

## app/agent_plan_orchestrator.py

225行；SHA256 `2df8413e1c13110dd543244ca5513b702eafe49db86164bf5e509d4f8d3798c1`。

Pure single-step state machine for goal-driven agent plans.

顶层定义：_utc_now、_validated_plan、_step_index、_replace_step、_event、start_plan_step、await_dynamic_confirmation、finish_plan_step、cancel_plan

## app/agent_plan_recovery.py

256行；SHA256 `2c1d4f890ec14cf752abcb6d2d535cddd93caff63e2ef18ed747b8696d1368d8`。

Pure recovery decisions and transitions for failed plan step results.

顶层定义：PlanRecoveryDecision、_failure_codes、decide_plan_recovery、_recovery_transition、start_deterministic_repair、resume_plan_step_after_repair、request_plan_replan、apply_replanned_steps

## app/agent_plan_runtime.py

364行；SHA256 `fba49dc58b296476516eb610791659bf293581149dbd74c5c445ea74d091e8d2`。

Strict execution-plan control around the existing chat domain executor.

顶层定义：AgentPlanSession、_default_store_path、_tool_name、_risk_level、_targets、AgentPlanExecutionController

## app/agent_plan_sqlite_store.py

258行；SHA256 `57149c8d3f2cfeb9b1010fde5840fbdb57eac2b89d68805053d6ee61c6039a14`。

Transactional SQLite persistence for agent plans and append-only events.

顶层定义：SQLiteAgentPlanStore

## app/agent_plan_store.py

138行；SHA256 `8071e1ed6bd23a7956b4a902f77b11e250b288bd1c8213082ab1fc3d4e080fc3`。

Persistent plan snapshots with an append-only transition event stream.

顶层定义：AgentPlanStore

## app/agent_policy.py

64行；SHA256 `8c461f1bad570db21350791e1228ac0627b7594911230063fd1e7e58a44599ac`。

（无模块说明）

顶层定义：normalize_policy_mode、agent_tool_allowed、agent_tool_policy

## app/agent_response_builder.py

78行；SHA256 `ce6c8502f5c36a37340e872837ccdac7c2c474d241ca0c27673513fcd869e46f`。

Pure response adapters; no CAD execution, storage or model requests.

顶层定义：normalize_acceptance_response

## app/agent_run_store.py

310行；SHA256 `a492a4db89d0e994076a378a740fa354f12b757c211667b273f48c3789f2b49d`。

（无模块说明）

顶层定义：AgentRunStore

## app/agent_service.py

11566行；SHA256 `7f28f5ac9aae3606ac3b3e43f8d7a0399cb791061badf3c0b7d4bcfbfeb93a38`。

（无模块说明）

顶层定义：_extract_upper_bound_dimensions、PendingAction、RobotAgentService、set_request_execution_context、reset_request_execution_context

## app/agent_service_config.py

40行；SHA256 `80f6539bc7bd991c40d11574ea69c930954ccbd0dc5b7f9a897c08cd0efc3cb7`。

Static model-provider configuration for the agent service.

顶层定义：无

## app/agent_service_context.py

96行；SHA256 `d03a587281b838e2e408a0429a5bd5a6643afff0cc9c4889b247a8d391a9d717`。

Small, side-effect-free helpers shared by the agent service workflow.

顶层定义：project_id_from_route、conversation_id_from_route、merge_design_requirements、template_geometry_count

## app/agent_service_policy.py

65行；SHA256 `2c60744a6bcb1f50583389752d8d5f5a34891ccfe60156ec44cef83ccdc0e3b1`。

Provider-independent conversational policy for the robot agent.

顶层定义：无

## app/agent_skills.py

2490行；SHA256 `58120a6f3fd57c965b17cbd893e8c8d215d5e57a824e7fbb9af592bdb710918c`。

（无模块说明）

顶层定义：validate_preview_paths、inspect_drawing、list_elements、validate_drawing、diff_drawings、snapshot_drawing、apply_drawing_modifications、_positive_quantity_before_template、_template_layout_requirements、normalize_template_layout_for_matches、recognize_drawing_template、_placement_hints、recognize_drawing_template_set、compose_template_geometries、compose_template_instance_count、_rectangle_points、drawing_template_geometries、_template_bounds、build_template_logical_object_graph、drawing_template_motion_steps、_default_printer、heart_outline_geometry、parameterize_design、clarify_requirements、calculate_geometry_bounds、validate_template_layout、_orientation、_on_segment、_segments_intersect、_intersection_key、analyze_geometry_topology、_geometry_points_for_validation、check_drawing_feasibility、score_design_variant、layer_drawing_paths、recommend_recovery

## app/answer_validation.py

480行；SHA256 `e6e82a595231f36cafa77cf98d4dda369bd6c85102324bbe3b190d4d02278d32`。

（无模块说明）

顶层定义：_hide_development_report_sentences、format_agent_answer_for_display、compact_agent_answer、_issue、_drop_blocked_claims、_replace_number、_correct_fresh_numeric_facts、_correct_boolean_facts、validate_agent_answer

## app/audit_store.py

94行；SHA256 `928da3e14b91c1de8fc4b9aae49e2cad1eb3c6973b6bf7d1bc6301395c88ab7e`。

（无模块说明）

顶层定义：AgentAuditStore

## app/cad_assertion_authority.py

42行；SHA256 `075beb7468a081c5dd4a05fc09390ac940f60be3aa4606b22479b7b5df168f16`。

Resolve model bounds only through complete independent source evidence.

顶层定义：reconcile_model_bounds

## app/cad_assertions.py

263行；SHA256 `384960e28bb46499d1e0f6cf08bb17360958d539911dfd1ae153db67d2849a88`。

Unified blocking assertions for deterministic CAD candidate persistence.

顶层定义：_fingerprint、_normalized_target、build_cad_machine_assertions、validate_cad_machine_assertions、repair_cad_machine_assertions_once

## app/cad_axis_requirements.py

87行；SHA256 `82cb52907e87fab17d5b5680c740f06b690fd6408cb05ac1c78e66b4b80151dc`。

Source principal-axis dimensions; no geometry generation or model claims.

顶层定义：ellipse_axes、verify_ellipse_axes

## app/cad_candidate_orchestrator.py

405行；SHA256 `6f64f0fc77b3b1917f9b748d1ee107f367bf8f42951b4707c5b9609909372ab5`。

State-machine decisions for deterministic CAD candidate orchestration.

顶层定义：persist_candidate_variant、design_confirmation_gate、candidate_preflight、restore_existing_candidate、prepare_new_candidate、persist_prepared_candidate

## app/cad_candidate_state.py

146行；SHA256 `4b8d058eba1c89bd50c9dda3c628f05ad7e6dff15a1a253e093814518a518011`。

Shared candidate eligibility for restore, selection and editing.

顶层定义：geometry_evidence_hash、bind_version_symbols、resolve_version_symbols、transformed_version_symbols、candidate_is_reviewable_draft、bind_creation_history、candidate_is_accepted、authoritative_acceptance_summary、accepted_project_view

## app/cad_canonical_json.py

13行；SHA256 `031700e78fed433ad5fa3645d0b0d0fa4b9b5732ffb8aa42fc81610549227b05`。

Existing canonical JSON/SHA256 protocol; keep historical bytes stable.

顶层定义：canonical_json_hash

## app/cad_capsule_acceptance.py

102行；SHA256 `453e22f124cb0631ce305724b4217c69d96baa664d22f23af421995a38d13438`。

Read-only stadium boundary measurement and fully scoped source proof.

顶层定义：measure_capsule、has_local_axis_dimensions、capsule_source_requirements、verify_capsule_source

## app/cad_circle_group_acceptance.py

93行；SHA256 `8fc939a6241d7967dcf181c3b8e095d1eb33eefaef82d5d4333957d0f53a3506`。

Bind a counted circle group to measured radii and pair relations.

顶层定义：verify_circle_group_source

## app/cad_composition_addition.py

123行；SHA256 `668bef3848ca92b13572856291e7f68d3e6d0657e90fb01dc8197f1b5099e0c2`。

Compile explicit relative additions into the shared CAD construction IR.

顶层定义：_millimetres、parse_relative_additions、execute_relative_additions

## app/cad_composition_coverage.py

171行；SHA256 `a7948df38a36143586163955b10210f45de2077aa3bd3e1838d46a1d8d08a248`。

Connect existing composition measurements to fully consumed source text.

顶层定义：verify_composition_coverage、_verify_named_coverage

## app/cad_connection_direction.py

66行；SHA256 `1a5a254ac4608da582facd3a3802785d3c354fe3416c4d03ace2338ba46cc584`。

Resolve a two-valued arc traversal from source-required tangent joints.

顶层定义：resolve_tangent_arc_directions

## app/cad_constraint_solver.py

562行；SHA256 `67916c0fe5955d5ce33cb20d7349f2f8a2cfe41b0c40d8419c8d94115984b43c`。

Deterministic geometric-constraint solving for construction candidates.

顶层定义：ConstraintSolveError、_StrictModel、_BinaryConstraint、ConcentricConstraint、ParallelConstraint、PerpendicularConstraint、EqualRadiusConstraint、EqualSizeConstraint、CenterDistanceConstraint、EndpointCoincidentConstraint、available_constraint_backends、solve_geometric_constraints、_run_native_solver、_verify_native_scope、_single_geometry、_apply_constraint、_constraint_residual、_endpoint、_points、_center、_size、_direction_angle、_translate、_rotate、_scale、_normalize_signed_angle

## app/cad_construction.py

2111行；SHA256 `56ee881a5616d34a22f9cc377b1b3bf8c8f0c07b4298c7f6c20d66e9e3b9ea68`。

Strict, deterministic construction plans for the generic 2D CAD PoC.

顶层定义：ConstructionPlanError、_StrictModel、ConstructionPoint、ConstructionSemantic、ConstructionStepBase、AddLineStep、AddPolylineStep、AddRectangleStep、AddCenteredRectangleStep、AddCircleStep、AddArcStep、AddEllipseStep、AddBezierStep、AddSplineStep、CompositeLineSegment、CompositeBezierSegment、CompositeSplineSegment、CompositeArcSegment、JunctionConstraint、AddCompositePathStep、AddRotationalPathStep、_expand_rotational_path、AddParametricCurveStep、RectangularArrayStep、TemplateInstanceSpec、AddTemplateStep、EntityCountAssertion、BoundsSizeAssertion、ClosedAssertion、RadialPatternAssertion、CenterDistanceAssertion、AreaAssertion、ConstructionBudgets、FreeOutlineLayout、CadConstructionPlan、execute_construction_plan、construction_plan_json_schema、construction_geometry_bounds、construction_geometry_area、_apply_free_outline_layout、_predicted_entity_count、_execute_step、_effective_composite_samples、_sample_composite_path、_validate_composite_path_quality、_sample_composite_segment、_path_edges、_duplicate_edge_count、_self_intersection_count、_segments_intersect_with_tolerance、_composite_continuity、_segment_endpoint、_segment_derivative、_segment_tangent、_vector_angle_degrees、_maximum_polyline_curvature、_maximum_composite_sampling_error、_point_to_segment_distance、_segment_start、_segment_end、_point_distance、_bezier_point、_bspline_point、_clamped_uniform_knots、_translate_geometry、_logical_object、_refresh_logical_object_bounds、_array_logical_objects、_safe_object_id、_run_assertions、_run_single_assertion、_fail_assertion、_closed_geometry_area、_bounds、_xy

## app/cad_construction_commit.py

295行；SHA256 `e01a118aa6d6ff80bd8f46e93a6f00108fb007b3c455d1ebaf9f7e0dbe0e235f`。

Persist verified generic CAD construction results as design candidates.

顶层定义：ConstructionCommitError、retain_failed_construction_source、commit_construction_interpretation、_verified_candidates、_construction_record、_single_candidate_title、_project_name

## app/cad_construction_evaluation.py

224行；SHA256 `f29170453870a9ce4b00587c9bcbefadc706853e5e7c569a691a0ba03c2b1c0e`。

Read-only benchmark utilities for generic natural-language CAD construction.

顶层定义：evaluate_construction_interpretation、load_construction_benchmark、run_construction_benchmark、_evaluate_case、_provider_summary

## app/cad_construction_interpreter.py

3434行；SHA256 `e195c1071938eb82b8376d7b00deb6bd6db1c18b7eccd346f4fdc203b7d7e92a`。

Production interpreter for template, rule and structured-model construction.

顶层定义：_coerce_model_payload、_StrictModel、ConstructionClarification、ground_size_clarification、StructuredConstructionInterpretation、StructuredSketchGraphInterpretation、clarify_construction_request、construction_interpretation_json_schema、sketch_graph_interpretation_json_schema、interpret_sketch_graph_candidates、interpret_construction_request、construction_acceptance_summary、bind_component_layout、bind_sector_winding、compile_composition_plan、_composition_relation_checklist、bind_named_radial_requirements、_explicit_line_inventory、outline_requirements、bind_outline_requirements、normalize_construction_request、_requested_area_square_metres、normalize_explicit_area_once、_request_construction_schema、bind_explicit_outline_center、normalize_explicit_outline_size_once、normalize_composite_path_connections_once、_align_free_cubic_joints、_scale_area_step、_scale_points_about_centroid、_normalize_u_shape、_named_point、_format_number、repair_construction_references_once、_trial_plan_without_assertions、_target_is_provably_open、_repair_assertion_scope_or_rotated_bounds、_repair_global_centered_rectangle_bounds、_construction_size、_size_matches、_near、_construction_reference_records、_reference_key、_matching_output_refs、_matching_assertion_output_refs、_predicted_output_counts、parse_rule_construction_plan、_parse_clause、_to_m、_rotated_rectangle_bounds、_point、_first_point_after、_angle、_label_for_clause、_object_type、_evidence_is_grounded、_failure

## app/cad_coordinate_requirements.py

96行；SHA256 `dfa90a8794242ac226669e622459151ed22e24d578388576dd882dff94a20e30`。

Recognize explicit coordinate scale, without constructing a curve.

顶层定义：coordinate_scale、verify_control_point_curve

## app/cad_counterfactual_guard.py

266行；SHA256 `f9307c94ef238bc62175f55fd8a75030b50e9e88cb40e9f3f7845bf21caf5797`。

Reject CAD follow-up contracts whose changed fields lack user evidence.

顶层定义：_same、_contract_sha256、_report_sha256、_target、_parameter_changes、_parameter_evidence、_parameter_value、_finish_report、validate_counterfactual_followup、validate_counterfactual_guard_report

## app/cad_creation_intent.py

88行；SHA256 `d92294033ef2183adf5048429fa2dd70eb797e7cf0d05524bee703340709163f`。

Sentence-local creation scope, independent of supported geometry names.

顶层定义：has_compound_primitives、local_creation_objects、has_local_plural_reference、historical_reference_text

## app/cad_curve_fit_acceptance.py

148行；SHA256 `f3e2e94af19c3513e6c13c3333f3b34477f294b3c798c9e3626a636588324fb1`。

Measure curve identities from actual geometry; never construct curves.

顶层定义：_valid_boundary、verify_astroid、verify_cardioid、verify_native_semicircular_arch、verify_semicircular_arch

## app/cad_edit_chain.py

127行；SHA256 `1bf0d08cdb128e80ddc70876467f60e01e0636b53e01929c07d527c3bdb3ec08`。

Parse and atomically replay ordered CAD edits on stable targets.

顶层定义：_target_prefix、_target_signature、parse_incremental_edit_chain、replay_cad_edit_chain

## app/cad_edit_contract.py

526行；SHA256 `ab20e62bedbe13fa3d6c8e1e7d2a41208ccd44d5af7533b1a4c48bab5a87c77d`。

Validated, machine-readable contract for deterministic CAD edits.

顶层定义：CadEditTarget、CadEditParameters、CadEditSelector、CadEditCommand、build_cad_edit_contract、build_cad_edit_chain_contract、cad_edit_contract_to_edit

## app/cad_edit_gate.py

666行；SHA256 `bec690faef4c1b9cefd5dc86204f6416d61e497d4405cf946be0498342fded1f`。

Preflight and risk classification for deterministic CAD candidate edits.

顶层定义：geometry_fingerprint、geometry_entity_fingerprint、build_rejection_rollback_evidence、_semantic_geometry_fingerprint、validate_declared_edit_effect、_finite_coordinates、_positive_id、validate_split_shared_boundary_provenance、validate_target_change_scope、build_cad_edit_preflight

## app/cad_edit_intent.py

295行；SHA256 `865851502a2fc2e16889bd3fd7eddbcc647452db1db4681eed0636f6fd851cd5`。

Normalize natural-language CAD edits before deterministic execution.

顶层定义：_unique、_target、_derived_constraints、_auto_decisions、_missing_parameters、build_cad_edit_intent、cad_edit_intent_clarification、apply_intent_metadata

## app/cad_edit_interpreter.py

391行；SHA256 `ef31c8b37f21bab60855810be3217e7b00f3ca3bc50f16fbdaefbb2553628ca2`。

Strict model-output adapter for CAD edit language outside rule coverage.

顶层定义：StructuredCadTarget、StructuredCadParameters、StructuredCadInterpretation、_numbered_instances、_distance_values_mm、_contains_number、_direction_grounded、_ground_interpretation、_contains_forbidden_geometry、_legacy_target、parse_structured_cad_interpretation

## app/cad_edit_plan.py

568行；SHA256 `827717525e1c5a589f601e0079e71de5e44d8ed98dd937a44422f7a2adeddd39`。

Compile CAD edit contracts into deterministic, verifiable change plans.

顶层定义：_ids、_canonical、_semantic_target_ids、build_cad_edit_plan、_build_cad_edit_chain_plan、verify_cad_edit_plan、repair_cad_edit_plan_once、_verify_symmetric_rectangles

## app/cad_edit_preview.py

144行；SHA256 `a4f9869d104a5a18863e9dcf39394ee3a1d46527b2faa9a0aa703f8bf5600a38`。

Deterministic, read-only preview contracts for CAD candidate edits.

顶层定义：_fingerprint、_geometry_ids、_normalized_contract、build_cad_edit_preview、validate_cad_edit_preview

## app/cad_edit_relation_acceptance.py

89行；SHA256 `9a80d49608348c4d461bacf1fdbde93711109a29341a357e971a96be34fda40a`。

Measure compiled object relations independently of transform parameters.

顶层定义：_primitive、validate_edit_relations

## app/cad_edit_session.py

157行；SHA256 `375cee8f7152895fa1e3cab606baf35b0dc4617d5df1cb0d54d8b79c725ce31f`。

Source-preserving continuation of an unfinished edit, never a geometry writer.

顶层定义：fresh_creation、edit_text、selection_binding、binding_key、pending_binding、binding_matches、continuation、remember_edit

## app/cad_generation_recovery.py

93行；SHA256 `7c6d0bab1ec2acc3837c992c36872613609d1d0477aa71d4f994f483bf3c25b1`。

Bounded CAD recovery evidence; no implicit background jobs.

顶层定义：recovery_category、should_repair、bounded_repair_available、confidence_only_repair、recovery_record

## app/cad_geometry_measurements.py

171行；SHA256 `484b19303405c95cf11035983747804d20d9724a986bbdf688f21fe3c0224e1a`。

Shared geometry facts. No source interpretation, acceptance or generation.

顶层定义：measured、closed_polyline_points、straight_polyline_corners、rectangle_frame、circle_facts、polygon_circumcircle、polygon_circumcircle_diagnostics、rounded_rectangle_facts、arc_facts、path_geometry_facts、measure_path_geometry、ordered_straight_path

## app/cad_import.py

715行；SHA256 `8b108605ee91c17531a5d0ab1c1c644bc36f51187175d48266d7d1d4d373744c`。

Convert DXF entities into the canonical XLine CAD JSON format.

顶层定义：_resolve_converter、dwg_converter_status、convert_dwg_to_dxf、convert_dxf_to_dwg、classify_layer_semantic、classify_layer、_layer_properties、inspect_dxf_layers、parse_dxf、export_dxf

## app/cad_length_units.py

58行；SHA256 `77f5f2a57e55e91b7490247e1e94d60a7509640dbd87ac0703c99c29f4dc8d30`。

Shared length factors with explicit output units and legacy table types.

顶层定义：length_factors、planning_unit_contract

## app/cad_local_repair.py

201行；SHA256 `e77d04fea982f73320d0a344062ae50562d05452afbb2c75eb7d79509e43164d`。

Conservative locks for measured failures in independent literal paths.

顶层定义：fingerprint、coordinate_patch_schema、coordinate_patch_example、apply_coordinate_patch、subtract_rectangle_vertices、build_local_repair_scope、validate_local_repair

## app/cad_object_constraints.py

140行；SHA256 `4b4ce44a36a2b4888f52e517dd9cfc51d6a0ddf56ae110e166f54883c3f01895`。

Compile source-bound object constraints to the existing transform pipeline.

顶层定义：compile_object_constraint、compile_concentric_edit

## app/cad_parametric.py

240行；SHA256 `973a966cebd51f12e940788b33fb1723e9bcff5fe98a3625dec5134f96740736`。

Bounded arithmetic expressions and adaptive sampling; never executes code.

顶层定义：ParametricError、expression、construction_expression_errors、sample_curve、polar_requirements、verify_polar_requirements

## app/cad_path_relation_acceptance.py

270行；SHA256 `7c6adc281a37542f03004dff5ce27191ef5e720c8543b07ed14a4876b9d9866d`。

Measure source-requested path relations; never synthesize or repair CAD.

顶层定义：assemble_closed_boundary、path_relation_requirements、verify_path_relations、verify_path_source_coverage、perpendicular_arm_requirements、verify_perpendicular_arm_dimensions

## app/cad_plan_component_repair.py

115行；SHA256 `c0751e7d6ccf324cedc1e49b37eb456256513d550b19b438b1ff30eed78ae95d`。

Merge only measured failing components; preserve every other plan relation.

顶层定义：normalize_component_repair_context、merge_component_repair

## app/cad_plan_recovery.py

101行；SHA256 `936c5d81667a5d74885f0d7ed2d79fc6b3b35354820908a0ca43d89637be455b`。

One-shot deterministic CAD recovery for a verified plan step candidate.

顶层定义：CadPlanRecovery、verify_and_repair_cad_plan_step_once

## app/cad_plan_references.py

102行；SHA256 `558416b08a3e8cfe46f76826cdb243e6474e9e1df2693d73511fba97419f693f`。

Pure reference compilation shared by every construction-plan consumer.

顶层定义：plan_reference_catalog、bind_plan_references、plan_reference_errors

## app/cad_plan_verifier.py

146行；SHA256 `69c255cc90c5a26aab5ea0b476b30f8e7ed9e73d10d77d7d9bdd0c878d628800`。

Adapt the existing CAD validation chain to agent plan step results.

顶层定义：CadPlanVerification、_utc_now、_failure_message、verify_cad_plan_step

## app/cad_polar_source_coverage.py

37行；SHA256 `041953870cf15aff17288724c8e0295ff787a8533f8507388b90a05212c79551`。

Consume only source clauses covered by measured origin-based spiral checks.

顶层定义：verify_polar_source_coverage

## app/cad_precision.py

16行；SHA256 `dc08e0ba95ec299a639e71d6b51d0bafe051b4b451b1368494c58443cf9b5ced`。

Internal millimetre precision budget shared by construction and measurement.

顶层定义：bounded_sampling

## app/cad_primitive_layout_acceptance.py

277行；SHA256 `e755311e85928d43fa24599d3c2b7766cde21e790cf06b5974481ad8977280bf`。

Measure fully specified primitive layouts without using model labels or plans.

顶层定义：verify_primitive_layout、cylinder_view_requirements、_cylinder_views_source、_SourceProof、_rounded_source、_cross_source、_diameter_source、_face_source

## app/cad_project_candidates.py

1142行；SHA256 `a31aa2e7a944af978c8c2f399b34b8c7fa2c34cef195e9d38443002cd94211c9`。

Pure candidate-selection and whole-design geometry transforms.

顶层定义：assess_reusable_variant、candidate_variant_metadata、candidate_requirement_readiness、is_generator_supported_shape、_normalize_shape_value、_normalize_dimensions、normalize_design_requirements、_geometry_extent、_scale_geometry、_scale_geometries、normalize_model_geometry_units、candidate_response_payload、candidate_generation_context、validate_candidate_geometries、design_geometries_for_project、project_logical_graph、template_instance_assessment、template_instance_count、scale_factor_from_message、effective_parent_variant、scale_geometries

## app/cad_projection_acceptance.py

141行；SHA256 `2db038b96433e446d9ce3ef73f2c34370cd69e97a95f6ade1421bb85c251123f`。

Measure projected parallelotope edges; never construct or persist geometry.

顶层定义：projection_requirements、projection_clarification_is_redundant、verify_projection_requirements、verify_projection_source_coverage

## app/cad_radial_attachment_acceptance.py

65行；SHA256 `efa22a9301a736696c110b88fbea7e9041a3e48edff07d50b40f899f6a719c3d`。

Measure circle-bound radial line inventories; never construct geometry.

顶层定义：verify_radial_attachment_source

## app/cad_rectangle_acceptance.py

94行；SHA256 `8d47e292f91611f7c700f14797855ddd1757b910f40193177a5f214ae214ac95`。

Measure a fully consumed single-rectangle requirement without making geometry.

顶层定义：verify_single_rectangle

## app/cad_relation_acceptance.py

128行；SHA256 `545414a17785ccd53ad9e739baa6a89d3adae74448030f48d2a0988ece952474`。

Conservative source-bound relations over independently matched primitives.

顶层定义：extract_named_relations、_region、_corners、_inside、_disjoint、_endpoints、verify_named_relations

## app/cad_repetition_acceptance.py

374行；SHA256 `9964128bd99242ce80bcc37041def8e62b17c96c3a90ac195d8febd9400fcf42`。

Source-grounded checks for local dimensions, tiling and rotational symmetry.

顶层定义：mm、tiling_structure_requirements、parallel_strip_requirements、tooth_boundary_requirements、branch_structure_requirements、branch_attachment_dimensions、branch_source_ready、validate_repetition_plan、_staggered_grid_matches、verify_repetition_requirements

## app/cad_repetition_source_coverage.py

145行；SHA256 `1c0d1b94b09f8f9bd9de862366089e6e8300bf8ff5d6370a227464e598b067bf`。

Bind fully consumed repetition prose to existing measured geometry.

顶层定义：verify_repetition_source_coverage

## app/cad_requirement_contract.py

245行；SHA256 `2671fa4a831f069a1ec486e19f5bac92ffa6fe70c8de85aed9f230247d6af320`。

Conservative, source-bound scalar requirements; never infer missing scope.

顶层定义：project_requirement_state、requirement_contract、build_requirement_source_index、validate_junction_source_refs、junction_intent_guidance、inherit_requirement_source_index

## app/cad_requirement_ledger.py

178行；SHA256 `c1d48c026545bf18692cc67a08411973b68275b91c53786416172e672a8b04d5`。

Immutable source ledger; model assumptions never become user requirements.

顶层定义：project_requirement_ledger、_revision、candidate_requirement_snapshot、evidence_items、requirement_ledger、bind_geometry_acceptance

## app/cad_revision.py

201行；SHA256 `33fd359006c75a1a4c9926197cff5bd4505350d00bc7ed82f7596b7f9ad1dbd9`。

Unified diff, validation, snapshot and rollback contract for CAD revisions.

顶层定义：build_cad_revision_contract、verify_cad_revision_state、verify_variant_revision_for_planning、_planning_source_result

## app/cad_selected_operations.py

81行；SHA256 `73af7a3c2bd263f6c755cc8e5376abfa3f1f9fa1ac71e1800661ffa59c0ff18d`。

Generic selected-geometry transforms, independent of template instances.

顶层定义：apply_selected_operation

## app/cad_semantic_acceptance.py

403行；SHA256 `4d06f5432b7995087cd086e5794e72bf7be1528359028d1ab3a396deb022d348`。

Measure narrow canonical straight-line profiles; never generate geometry.

顶层定义：nested_frame_requirement、regular_polygon_requirement、semantic_requirements、_corners、verify_semantic_requirements

## app/cad_semantic_source_coverage.py

435行；SHA256 `369cb88596c71d0d7fd89afffe26c9774c8571d485029b26115c374860da84aa`。

Consume source text only for independently measured semantic contracts.

顶层定义：semicircular_source_requirements、verify_semicircular_outline_source、source_dimension_relation_guidance、verify_polygonal_outline_source、verify_periodic_outline_source、verify_measured_semantic_coverage、_astroid_formula_source、_house_source_coverage

## app/cad_shared_points.py

35行；SHA256 `a2dc562b43a00491afa2a8031f66f441c105ab30603212993a6fc535929319ec`。

Resolve explicit coordinate references through the existing safe evaluator.

顶层定义：resolve_shared_points

## app/cad_sketch_graph.py

329行；SHA256 `d414bee0639a5a32e2fc1dae8ae9583a54d599ab4c964f81cf19b2356b2ec31e`。

Isolated SketchGraph candidates for generic 2D CAD construction.

顶层定义：_StrictModel、SketchGraphCandidate、SketchGraphCandidateSet、SketchGraphNode、SketchGraphEdge、SketchGraphConstraint、SketchGraph、sketch_graph_candidate_set_json_schema、evaluate_sketch_graph_candidates、build_sketch_graph、_candidate_score、_geometry_fingerprint

## app/cad_source_acceptance.py

526行；SHA256 `e4b6fcc3f7b88fd4d073e8b9e5aec79efdf248939f80a32995df5c12ddc85c83`。

Source-scoped primitive checks. No geometry creation or model assertions.

顶层定义：source_texts、verify_single_round_primitive、nested_circle_roles、verify_final_source_contract、extract_scoped_primitives、verify_scoped_primitives

## app/cad_source_intent.py

39行；SHA256 `09eaa4d2da34042982b6f534e8cdf06538cfd988a299a7d83e01695e92444da2`。

Recognize explicit preview-only intent, preserving every other source clause.

顶层定义：partition_preview_intent、partition_outline_scope、verify_output_restrictions

## app/cad_standard_templates.py

95行；SHA256 `28d0ef660a0ac6bdb36e6941a1642be4ba58be18733fcffc8db088adb2538f26`。

Nominal main court line paths, in millimetres; no paint-edge compensation.

顶层定义：template_profile、court_geometries

## app/cad_stroke_acceptance.py

112行；SHA256 `b0f4af1ae0d32be8c695ecee91ead354670a16e0590289fcb497ba3b30f44fe5`。

Verify explicitly supplied two-stroke chains and a horizontal cross stroke.

顶层定义：stroke_requirements、verify_stroke_requirements、verify_stroke_source_coverage

## app/cad_structure_contract.py

573行；SHA256 `793bd7fde846e6a07eb32cd40d1e26814d9ba786252e30d35468808829c8b0ee`。

Source-backed component contracts. Checks geometry; never constructs it.

顶层定义：StructureContractError、validate_plan_structure、reference_contract、explicit_dimensions、explicit_composition、validate_explicit_composition、_validate_geometric_relationships、_points、_corners、_frame、validate_structure

## app/cad_symmetric_divider_acceptance.py

60行；SHA256 `f6d890568a90fc605aa28e42efa26c342c16a73d7787bffd1d007343034973aa`。

Measure native circular boundaries, an S divider and paired circular holes.

顶层定义：verify_symmetric_divider_source

## app/cad_target_resolver.py

844行；SHA256 `151b6dd2b71ad37e650b88dd78eef6ef590ea41c4361a339bc6991642e7c0904`。

Deterministic target resolution for structured CAD edits.

顶层定义：recent_creation_selector、resolve_created_target、_authoritative_scoring、_score_extreme_candidates、_score_decision_reason、_stable_spatial_candidates、resolve_logical_object_target、validate_logical_object_target、logical_object_topology_conflict、validate_split_shared_boundary_target、_points、_bounds、_clarification、resolve_cad_target、bind_resolved_target

## app/cad_template_plan.py

159行；SHA256 `8ff420a693c9201f43fbb7f2b0469bda7cb09d11b98cc4ed3ea431146d3e7f0b`。

Compile confirmed template parameters into the common construction IR.

顶层定义：template_covers_request、template_plan_for_project、template_trial_acceptance、interpret_template_project、template_plan_from_text

## app/cad_validation_evidence.py

27行；SHA256 `bd182253ed09f8d8fc39d5e63f2faad590656c5ff9d88ea9725278f0ec13c77b`。

Evidence owned by one construction trial; no process/request-global cache.

顶层定义：ConstructionEvidence

## app/cad_vertex_acceptance.py

225行；SHA256 `095a9632fae1851a6443f437386eed57f092430c2e6271cbcb49c1e6f625db58`。

Read-only source-coordinate proof for a single closed straight vertex path.

顶层定义：normalize_relative_walk_source、open_straight_path_requirements、verify_open_straight_path、verify_vertex_path

## app/cad_visual_scoring.py

150行；SHA256 `3a78a9975125daf24180ef7897e34207a97fb68297afa473a2ef68e20bade818`。

Advisory raster scoring for already geometry-validated CAD candidates.

顶层定义：score_candidate_visuals、_report

## app/cad_wave_requirements.py

85行；SHA256 `40ecb75ea03933bf4c64ac5e66c73b2a468cd63b194f3c0a327898705069c37a`。

Source-bound harmonic measurement of submitted wave linework; no CAD creation.

顶层定义：wave_requirements、verify_wave_requirements

## app/config.py

125行；SHA256 `8b8f72430bee9a18d675b13b6d2920abbc339fffcf0f45274ae2b6ffa103416d`。

（无模块说明）

顶层定义：_optional_float_env、Topics、Services

## app/construction_quality.py

303行；SHA256 `7a61fa3dfacd2e1bdc9937d0554f9d175c271d1673dba1cfc63a0cdff06923e0`。

（无模块说明）

顶层定义：_finite、_point_m、_angle_delta、_profile、analyze_construction_quality

## app/conversation_archive.py

12行；SHA256 `bd6f4e2b6c6c9c1dfdfc5eadb24c611a85b59e50a83c27c4ff38c04756760aee`。

Durable deleted-chat snapshots, independent of model conversation memory.

顶层定义：archived_chats

## app/conversation_memory.py

1308行；SHA256 `9eb96fb806ba61cfd0892535230a2af62065743a156a9a90b6d454fb6f0e52fa`。

（无模块说明）

顶层定义：_now、ConversationMemoryStore

## app/creative_projects.py

1239行；SHA256 `412e3ad1bfb5e9cbe10ce4ae1eac561076f5f2c2b66ab332a5332d8eb94fe5fb`。

（无模块说明）

顶层定义：CreativeProjectStore、get_creative_project_store

## app/creative_workflow.py

1214行；SHA256 `68656bc4489b840e0ab00bdc257e5daaad9d2b5a0147207a5fdac214307b97f3`。

（无模块说明）

顶层定义：prepare_project_plan、refresh_project_plan、ensure_project_plan_ready、mark_project_execution_pending、stop_project_before_deletion、exit_project_plan、refresh_project_execution、_partition_status_for_stage、project_recovery_assessment、_current_mission_resume_assessment、resume_project_execution、prepare_project_recovery、build_project_acceptance_report、_project_printer、CreativeProjectSynchronizer

## app/database.py

840行；SHA256 `6626b2140a10782d3b073f8a715ede4fb90d027014192de259b8cf3d8df2c995`。

SQLite persistence for business history and telemetry.

顶层定义：_default_path、XLineDatabase

## app/deepseek_transport.py

141行；SHA256 `36e2831a5a23e30223c73ff89794d87b799a71c6744ff4096132b82becfffc95`。

Low-level DeepSeek HTTP transport with bounded streaming reads.

顶层定义：DeepSeekTransport

## app/diagnostics.py

249行；SHA256 `0371d7f123dd755aa4d79c0e59ff1c26323d6073468881f7a0815e463991d036`。

（无模块说明）

顶层定义：build_link_diagnosis、build_local_diagnosis、compare_api_with_local

## app/discovery.py

190行；SHA256 `46b7aa42a31a1505b6729a04d1757815af640df52f3b586ead121255b55055c7`。

Local-network discovery for Dashes rover backends.

顶层定义：_device_identity、_local_ip、_labels、_record、RoverDiscoveryService、main

## app/drawing_commands.py

260行；SHA256 `54b28c33a5e776acf296ea2ea336aa4c443b5e0f882b12d541c04728f993cc1c`。

Versioned, deterministic command protocol for AI drawing edits.

顶层定义：_canonical、_digest、_entity_id、drawing_snapshot_id、build_command_rollback_evidence、build_drawing_commands、validate_drawing_commands、execute_drawing_commands、build_drawing_command_batch

## app/drawing_store.py

400行；SHA256 `5d29aa486b58c795889086cfad038df54679348dcf8bda496ffb5227a6a23ee1`。

（无模块说明）

顶层定义：cad_directory、available_drawings、resolve_drawing、drawing_execution_ready、preview_paths、geometry_preview_paths、_points_bounds、build_path_preview_contract、_geometry_points、_point、_valid_points、_number、_angle、_sample_circle、_positive_sweep、_sample_arc、_sample_ellipse、_sample_spline、_sample_text_bounds、_numeric_list、_clamped_knots、_basis_values、_close_if_needed

## app/drawing_versions.py

457行；SHA256 `2c79c3af6842a1888fad0fcc370b60c6ca582244078d12af4b200b8da767b1d6`。

（无模块说明）

顶层定义：DuplicateDrawingOperationError、DrawingVersionStore

## app/fault_evaluation.py

63行；SHA256 `5862d0405a4a22cff49f13e435c054d3110e65e8cd809b982651e1a81f1aeaaa`。

Read-only live vehicle fault evaluation.

顶层定义：evaluate_live_vehicle

## app/geometry_catalog.py

314行；SHA256 `b046ed24944589139f7e1ef6a6276e46aafc76cd9ed483cb7001ce9abeb3b4bd`。

Deterministic, compact semantic catalog for CAD entity targeting.

顶层定义：_number、_geometry_id、_points、geometry_bounds、_combined_bounds、_center、_meters、_explicit_semantic、_semantic_name、_instance_position_labels、_region_label、_layer_names_from_source、_topology_summary、build_geometry_catalog

## app/geometry_diff.py

261行；SHA256 `5cc1725d79365a13f8b4cdd237456ad21c6ed8850e749c25261dd52c20c93bf5`。

Compare canonical XLine CAD geometries without changing the source drawing.

顶层定义：_canonical、_fingerprint、build_geometry_diff、_path_length、_path_by_geometry、build_path_impact、build_diff_preview_paths、build_drawing_change_review

## app/geometry_identity.py

100行；SHA256 `b46cc34117f0c4b07d35a527c9c912301835de83f22e92e47f57cf5ac4046d75`。

Stable identity checks for versioned CAD geometries.

顶层定义：normalize_geometry_identity、validate_identity_continuity

## app/image_drawing_import.py

446行；SHA256 `7cb903766e2e2c7673b2234654f0e72088cc45e9b68387b3433def2d81304b51`。

Convert raster line drawings into the canonical XLine drawing schema.

顶层定义：_devkit_root、image_vectorizer_status、validate_image_upload、save_source_image、resolve_source_image、_point、primitives_to_app_lines、suggest_image_instance_groups、_geometry_segments、_segments_touch、_segment_distance、_point_segment_distance、_segments_intersect、_component_bounds、_component_sort_key、vectorize_image_to_drawing

## app/incremental_cad.py

2772行；SHA256 `f139191430c59f2fc03c2ca192cbf96e11f25dea5f7eac639a6a92b3c591ad41`。

Conservative, instance-scoped edits on an existing CAD candidate.

顶层定义：_attribute_or_spatial_selector、_millimeters、_instance_prefix、_translation_instruction、_compound_translation、_instance_numbers、_batch_rotation_pivot、_batch_scale_pivot、_scale_factor、_rotation_prefix、_scale_prefix、_legacy_previous_edit、resolve_incremental_correction、resolve_incremental_followup、parse_incremental_edit、parse_constrained_addition、add_symmetric_rectangles_on_circle、_split_shared_boundaries_for_edit、_points、_bounds、_translate、_rotate、_scale、_geometry_signature、_mirror_transform、_line_direction、_is_closed_loop、_array_rectangular_copies、_array_polar_copies、_apply_constraint_edit、_resize_selected_geometry、_resolve_edit_selector、edit_candidate_geometries、_edit_candidate_geometries、space_two_instances、rearrange_two_template_instances

## app/knowledge_retrieval.py

232行；SHA256 `3e1dcc8bdcf75fe0b4ba64839f9c86d6bf825418df411c68830b26b5c69110c9`。

（无模块说明）

顶层定义：KnowledgeChunk、ProjectKnowledgeRetriever

## app/logical_topology.py

970行；SHA256 `0e622944b8045ddd0ff5e1b34047d310f473a6d3e581e9cf0e382614b43add98`。

Validation and revision evidence for logical CAD objects and topology.

顶层定义：logical_graph_fingerprint、validate_logical_object_graph、build_confirmed_instance_graph、build_logical_object_diff、validate_logical_object_continuity、preserve_logical_graph、_adopt_new_template_instances、evolve_logical_graph_for_edit、logical_object_ids_for_edit、_normalized_topology、_prune_topology、_copied_object_id、_copied_label、_geometry_bounds、_refresh_changed_object_bounds、_bounds_are_reliable、_validate_spatial_relation、_normalized_bounds、_contains、_overlap、_shared_map、_positive_int、_canonical、_error

## app/main.py

59行；SHA256 `0ecf9cd64a0b3e1db07959979eb9891990434b533e71676c413d7e24fb341b27`。

（无模块说明）

顶层定义：lifespan

## app/mission_analysis.py

180行；SHA256 `f8920b4f885dce66fa3aa0a02ab7de9eac8c0534c9466a0bc3d43f69e1abe645`。

（无模块说明）

顶层定义：_number、point_xy、segment_endpoint_m、_polyline_length、segment_length_m、analyze_mission

## app/mission_ledger.py

200行；SHA256 `9feb4eb73df4c7ac2778e368b2dfce97d1820d6f6a017630ad0270f68754515d`。

（无模块说明）

顶层定义：MissionLedgerStore

## app/mission_quality.py

59行；SHA256 `07ad637bb711481123ca7181de7beec0a3ed1a55efbe0a8552a8a8384f5d5251`。

（无模块说明）

顶层定义：_heading、score_planned_mission

## app/mission_reports.py

65行；SHA256 `be55886a0ac3cb9da449c4d237fa8be5a82069a177e4e6622ea12fcc7274b594`。

（无模块说明）

顶层定义：build_acceptance_report

## app/model_providers.py

243行；SHA256 `dd1c9a2eaff52fb861a6f10051174914b18315ec0f3083f689f947767ceb8cf5`。

（无模块说明）

顶层定义：ProviderReply、ModelProviderAdapter、OpenAICompatibleAdapter、AnthropicAdapter、GeminiAdapter、provider_adapter

## app/model_request_gateway.py

79行；SHA256 `190c469e93cbf39aa556c3f6bbe6e7a97e92506a4728ea24bc0577a352f5dc70`。

Shared model-provider request boundary.

顶层定义：request_provider_tool_json、request_openai_responses_json

## app/native_constraint_worker.py

293行；SHA256 `6daf36f49df88cb0f13f0cb0bbed0566eeca94c322ca8a73b9dd2bead495f2f8`。

Isolated native PlaneGCS/SolveSpace worker.

顶层定义：_points、_center、_direction、_size、_translate、_rotate、_scale、_geometry_by_ref、_planegcs_pair、_slvs_point、_solvespace_pair、run、main

## app/network_manager.py

465行；SHA256 `a237687d387522231cf6941d7274254f6e1b36653b0d255e47e33927b890d6de`。

Restricted NetworkManager adapter for rover Wi-Fi provisioning.

顶层定义：NetworkManagerAdapter

## app/oscillation.py

33行；SHA256 `b1b5716a0cde5d05e9314d3a292fdf523549b82fb62d77cf411b88f0844bccbb`。

（无模块说明）

顶层定义：HeadingOscillationDetector

## app/project_ownership.py

43行；SHA256 `f9a0b62bbea5252d8a97bc0381ba6cf4edd40960c076e0532913acc48d502237`。

Request-local ownership, including generators resumed on worker threads.

顶层定义：owned_request

## app/request_context.py

32行；SHA256 `fa55637ae8f74d2b01b660db765362523f654f29a5228b29335df585ad72b6f4`。

（无模块说明）

顶层定义：current_agent_user_id、bind_agent_user_id、agent_user_scope

## app/ros_adapter.py

2968行；SHA256 `c274e299e5c016c2e648f931f69c39bc5de0c70a040d263a9a297f538b834b71`。

（无模块说明）

顶层定义：planner_cad_path、hardware_runtime_command、classify_planned_segment、planned_ink_fingerprint、RobotRosAdapter、RobotBackendNode

## app/rosbridge_protocol.py

371行；SHA256 `00785c4973985bde40bb8ed910826fd53265e21c44f4b1aca32df503a1992d14`。

（无模块说明）

顶层定义：handle_rosbridge_payload、_nested_number、_printer_unready_message

## app/route_optimization_comparison.py

156行；SHA256 `945d20b01cc63352c29bde1cf4b800aee24ef926a1fe193d388268c794e37558`。

（无模块说明）

顶层定义：_distance、_usable_paths、_evaluate_order、build_route_optimization_comparison、attach_ros2_result

## app/routers/__init__.py

1行；SHA256 `6afe91dfc6357f50d0e1be408ee471db6b82c2f77c1652778c2914fc94851f82`。

HTTP and WebSocket route modules for the FastAPI application.

顶层定义：无

## app/routers/agent.py

320行；SHA256 `1d91a7ec1beea560e9ab59c58a917d9875cfc4544033384fdc14bfe752c37c6e`。

（无模块说明）

顶层定义：agent_tools、agent_policy_evaluation、agent_knowledge_search、agent_status、agent_task_list、delete_agent_conversation_memory、project_recycle、conversation_lifecycle、project_lifecycle、get_agent_conversation_memory、decide_agent_requirements、agent_task_detail、agent_fault_evaluation、agent_audit_list、agent_case_list、agent_case_status、agent_case_promote、agent_template_validate、agent_template_accept、agent_config、update_agent_config、test_agent_config、upload_agent_image、agent_chat、agent_run_list、agent_run_detail、cancel_agent_run、resume_agent_run、agent_chat_stream、agent_confirm

## app/routers/device.py

149行；SHA256 `e44cd66c2e7be1a4c5549839c5313e4ab5f394e323c2188fa4b7d86f1e090e5c`。

（无模块说明）

顶层定义：device_capability_list、device_capability_detail、monitor_diagnose、cmd_vel、emergency_stop、printer、ln150、printer_active

## app/routers/drawings.py

817行；SHA256 `31d903518f8205850dcda79cf5cf4eafe5bc8feb72eda6acd7fa4602e8b7a94f`。

（无模块说明）

顶层定义：list_drawings、list_drawing_versions、drawing_version_history、rollback_drawing_version、cad_file_capabilities、export_drawing_dxf、export_drawing_dwg、drawing_source_image、drawing_preview、delete_drawing、save_drawing、import_drawing_json、import_cad_drawing、import_filtered_cad_drawing、update_drawing_layer_roles、drawing_analysis、import_image_drawing

## app/routers/missions.py

191行；SHA256 `12db0aea4fc3f1e40adb449e536b225ed8915d4758acac87d847fcfbdbffd3c4`。

（无模块说明）

顶层定义：mission_ledger_list、mission_ledger_detail、mission_reports、mission_report_detail、agent_plan_preview、agent_variant_plan_preview、agent_request_execution、mission

## app/routers/projects.py

457行；SHA256 `8b051fdd0787b8a96cb0609f5ba6c54735b62f9cd0382c4a3eb1710f01765baf`。

（无模块说明）

顶层定义：manual_cad_review、_guard_project_endpoint_binding、creative_project_list、create_creative_project、creative_project_detail、creative_project_timeline、generate_creative_project_candidate、update_creative_project、delete_creative_project、save_candidate_drawing、select_creative_project_variant、start_creative_project_iteration、confirm_creative_project_instance_groups、plan_creative_project、creative_project_plan_status、exit_creative_project_plan、request_creative_project_execution、creative_project_execution_status、creative_project_recovery、create_creative_project_recovery、resume_creative_project_execution、confirm_creative_project_recovery_inspection、generate_creative_project_report、creative_project_report

## app/routers/rosbridge.py

75行；SHA256 `234fe35db1385eeb2c4e5c1d1706c429c6162a964d41ab1e84641e25d6eaaac9`。

（无模块说明）

顶层定义：websocket_status、websocket_rosbridge

## app/routers/system.py

158行；SHA256 `4a8cdc0e9bb7c2c6bcbe0865538fbd1403fc12c3497f3e92028c553f22b3580c`。

（无模块说明）

顶层定义：health、status、telemetry_contract、telemetry_history、network_status、network_scan、network_connect、network_connect_saved、network_verify、network_wifi_disconnect、network_wifi_forget、database_summary、database_migrations、database_backup、database_integrity、database_cleanup、logs

## app/schemas.py

318行；SHA256 `0eaa5fd7071546a1d99a283e95ec9657bd07c7423309946cf29a09258da7d836`。

（无模块说明）

顶层定义：PhysicalCommand、VelocityCommand、PrinterCommand、Ln150Command、MissionCommand、EmergencyStopCommand、PrinterActiveCommand、ApiResult、AgentMessage、AgentAttachment、AgentChatRequest、AgentDrawingSelection、AgentRequirementDecisionRequest、DeviceDiagnosticRequest、WifiProvisionRequest、WifiNetworkCommand、AgentConfirmRequest、AgentDrawingPlanRequest、AgentConfigCommand、DrawingSegment、DrawingSaveRequest、DrawingJsonImportRequest、DrawingLayerRoleRequest、CadLayerFilteredImportRequest、DrawingVersionRollbackRequest、CreativeProjectCreateRequest、CreativeProjectUpdateRequest、CreativeProjectVariantSelectRequest、CreativeProjectIterationRequest、CreativeProjectSaveDrawingRequest、CreativeProjectInstanceGroupsRequest、RecoveryInspectionRequest、DatabaseCleanupRequest

## app/spatial_partition.py

841行；SHA256 `2093dbccbf0e58a9d219b1563e080332a4f919d3c7b2ec3adab583355166e4ac`。

（无模块说明）

顶层定义：build_spatial_partition、next_partition_zone、next_partition_segment、update_partition_zone、update_partition_segment、refresh_partition_summary、_source_paths、_path_bounds、_empty_zones、_split_path、_point_zone、_fragment_geometry、_continuity_links、_ordered_zones、_local_frame、_geometry_to_local、_local_projection_verified、_execution_segments、_refresh_zone_from_segments、_zone_id、_same_point、_path_length、_geometry_sha256

## app/state.py

651行；SHA256 `b6f55f584f03d4908162489cafba5f4611613f84197a1c7ed0c22430602d2dfa`。

（无模块说明）

顶层定义：now_text、normalize_mission_lifecycle、RobotState、_set_virtual_spraying、_stop_virtual_motion、load_virtual_mission_segments、start_virtual_mission_tracking、reset_virtual_mission_tracking、enable_demo_state、tick_demo_state

## app/structured_usage.py

73行；SHA256 `48ac03ba943242f1e3df94964bf2b7c714bb1f94f45d31a2834c156e18a24cfc`。

Request-local accounting for structured calls omitted by chat usage.

顶层定义：structured_model_fallback、remember_structured_model_fallback、structured_usage_scope、record_structured_usage、merge_structured_usage、usage_scoped_events

## app/task_store.py

228行；SHA256 `2ed48e5cbb95b3d5aca052f9fcf5329b16f588aeb3c2c532bf077bb677370870`。

（无模块说明）

顶层定义：utc_now、AgentTaskStore

## app/telemetry_contract.py

223行；SHA256 `78807a1ff31d381df682fc52be3a8ea4abac9333e05601b5022f5429cd04ce35`。

Stable, read-only contracts exposed to the App.

顶层定义：_positive_int_env、_quality、build_telemetry_contract、build_printer_contract、build_mission_contract、build_status_packet

## app/tooling.py

927行；SHA256 `17c980909eeb7cc8aba0ccd19911ed0d1d96992ed58174e8e98c63552a5be9de`。

（无模块说明）

顶层定义：ToolArguments、EmptyArguments、RectangleArguments、CadPoint、CadGeometryBase、CadLine、CadPolyline、CadCircle、CadArc、CadEllipse、CadSpline、CadTextAlign、CadText、CadBounds、CadLogicalObject、CadSharedGeometry、CadTopologyRelation、CadTopology、CadDrawingArguments、CadModificationTarget、CadGeometryPatch、CadAddOperation、CadUpdateOperation、CadRemoveOperation、ModifyDrawingArguments、ApplyCadCandidateEditArguments、DesignRequirementsArguments、CreateCreativeProjectArguments、UpdateCreativeProjectArguments、SelectDesignVariantArguments、CreativeProjectPlanArguments、DrawingFeasibilityArguments、ListElementsArguments、DiffDrawingArguments、SnapshotDrawingArguments、DrawingMetadataArguments、PathLayeringArguments、PreviewPathValidationArguments、DriveArguments、DriveSequenceArguments、MissionArguments、PreparedMissionArguments、Ln150Arguments、PrinterArguments、PrinterSprayArguments、ToolSpec、validate_tool_configuration、tool_catalog、GateDecision、build_action_preflight、validate_tool_arguments、authorize_tool、authorize_emergency_stop

## app/trajectory_comparison.py

92行；SHA256 `67299c4312754b1840463b3205156078a1091ee526440ee976679965d5c08fe4`。

（无模块说明）

顶层定义：compare_trajectories、_planned_polylines、_point_polyline_distance、_point_segment_distance、_finite

## app/user_model_config.py

86行；SHA256 `fe676a861de2c8e9d771846a5b608f9241183684a5676d9fcc0ab5f99a106395`。

（无模块说明）

顶层定义：UserModelConfigStore

## app/user_request_limits.py

63行；SHA256 `4fccd2b7746a09f7cc91137d0b156424bce1263967bbc384c7cadf3907d5a946`。

（无模块说明）

顶层定义：UserRequestLimitError、UserRequestLimiter

## app/web_demo.py

17行；SHA256 `eeeed2b0f0be7bd70f2e82aacf726253fe79dc959d19005618e34d2098cf8bf8`。

Refuse website proxy traffic unless this backend is hardware-isolated.

顶层定义：WebDemoMiddleware
